# Codex review: SMB I/O audit, Part 1

Reviewed `agent/smb-io-audit` at `36c2a12` against `486cf56` (commits `f9892fa`, `36c2a12`). This is a source review of the findings and the opt-in trace. The scenario's raw JSONL files were not retained; its summary tables are supporting evidence, not an independently replayable capture. The scenario ran on local APFS, so its call counts are HeLab operations, not measured SMB packets or timings.

## Findings

1. **Agree: unbounded `roots_verify` loop.** `helab/utils/folder_cache.py:1796-1803` changes `_mounts_observed` only on `mounts_seen`; `:1814-1829` requeues on every successful verification if its mount table differs. `_verify_roots` at `:1439-1453` queues both `volumes_verify` and `roots_verify`, and `helab/io_helper.py:552-572` makes the latter probe every known mounted root. Live's helper dispatch at `io_helper.py:2494-2498` does not emit `mounts_seen`. The reported 414 verifications in 30 seconds (`trace-session1.md:425-443`) are consistent with this loop, though the exact rate is machine dependent. **Fix direction: agree, with a state-machine qualification.** Trigger from a *new listing observation* that has not been requested, using `_verify_asked`, and do not requeue just because a verifier saw a newer OS table. Preserve a follow-up when a genuinely newer listing arrives while a verification is running, and handle failed verification without a busy retry. Avoid the duplicate volume verification per request. A time throttle is a useful backstop, not the primary correctness condition.

2. **Agree: Live saves do full load work.** `helab/views/FolderExplorer.py:1458-1468` starts an autosave after the configured number of new shots; `helab/utils/folder_cache.py:1283-1297` submits it as `load`. Ordinary `_load` lists and fingerprints every TXY (`helab/io_helper.py:1366-1395`), verifies all files (`:1598-1606`), then verifies again before a cache save (`:1631-1649`). Thus a successful save of N settled files normally makes about 3N stats, plus reads needed to assemble the dataset. **Fix direction: agree in principle, conditional on preserving identity, missing-shot detection, cache generations/budget and a consistent full dataset.** Live currently passes shot metadata, not the arrays held in the GUI; a dedicated save needs a safe way to provide/reuse those arrays. Merely trusting a sample of held files and skipping the full validation is insufficient for a durable cache.

3. **Agree: repeated Live listings and identity/sample checks during acquisition.** `io_helper.py:1778-1785` clears `live_since` while unsettled, and `:1790-1856` then lists, calls `_folder_identity`, samples held shots and stats all unheld TXY. `_folder_identity` walks marker paths upward (`:1684-1703`); each missing marker is still an attempted open. `FolderExplorer.py:1473-1476` also forces a listing after a minute. The scenario recorded 19 listing checks, 5 marker attempts per check, and 21 young-file stats (`trace-session1.md:261-303,507-517`). **Fix direction: partly agree.** Reuse the known marker path or location and recheck only pending files when the directory is unchanged; keep periodic full listings and an identity check before reusing held data after remount. Checking the marker only once per minute without another reliable remount signal would weaken the current protection. Reduce samples only with an explicit freshness/safety rule.

4. **Agree for the measured successful cached load, with scope.** `io_helper.py:1391` fingerprints every TXY; `:1562-1564` stats before and after each read; `:1602-1606` verifies the folder; `:1646-1648` verifies again before saving. That is five stats per successfully read file when disk saving proceeds, fewer for reused, uncached, failed or quick-check paths. Separate tree list/details and load paths explain the observed 2–3 listings (`io_helper.py:762,1021,1368`; `trace-session1.md` selection phases). **Fix direction: partly agree.** Using `DirEntry.stat` from the load's own listing is sensible (on macOS it can still incur a stat). Skip the second verification only when no source read or other relevant interval occurred after the first. Removing the before-read stat increases the race window; retain an equivalent integrity check, especially for writers and remounts. Sharing load and tree listings needs to preserve the tree's timely names and saved status semantics.

5. **Agree: no RAM-only quick check.** `io_helper.py:1354-1356` calls `_unchanged_since_cache` only with an open store. Without a root, a load proceeds to a full listing and `stat_files` (`:1366-1395`), followed by verification (`:1598-1606`); `trace-session2.md:167-188` reports 249 source operations for the RAM-only reselect versus six for a disk-cached folder. The exact total includes separate tree/details requests and depends on state. **Fix direction: agree with safeguards.** A RAM fingerprint/snapshot can support a sampled check, but keep its checked age, identity/remount handling, missing-shot detection, unsettled-file rules, and a forced full check for Retry/Refresh. A folder mtime alone is not enough.

6. **Agree: the current settle rule cannot establish writer completion.** Details use `entry.stat` (`io_helper.py:1021-1036`); loads stat files *before* `_settled` filters by age (`:1382-1399`); Live stats unheld files (`:1833-1849`). `_txy_complete` opens and reads the tail after age and two-observation checks (`:1711-1729,1843-1851`). Ordinary load does not call it: `:1562-1567` reads when the metadata matches before and after. A writer paused beyond five seconds can therefore still have a file open when Live reads its tail, and an ordinary load can parse, show, and save a stable half-file (`:1605-1619,1631-1659`). The summarized fake-writer trace records the tail open and the ordinary read during the write window (`trace-session1.md:507-523`); the 12,644/25,275-byte cache claim is reported by the worker, not independently proved from the retained raw trace. **Fix direction: agree that ordinary loads need protection, but age plus two unchanged looks cannot prove closure.** A writer pause at a complete row defeats even Live's tail test. Prefer a producer contract such as write-to-temp then atomic rename; until then use conservative read rules and mark results provisional. Decide separately whether metadata stats on young files are acceptable on the real SMB stack.

## Trace review

- **Off-state verdict: acceptable.** `TRACE` is None unless the environment variable names a file (`helab/io_helper.py:47-50`); wrappers use the original `os.stat`, `os.lstat`, `os.scandir`, `entry.stat`, `read_marker`, and `pd.read_csv` calls in that state (`:104-210`). GUI attribution is gated at `helab/utils/io_service.py:340-342,630-632`. The seven trace tests cover off-state writing/events, representative operations, helper attribution and Python-visible GUI access (`tests/test_io_trace.py:67-249`). This supports no behavior change with tracing off. Native Qt icon calls are outside the Python hook.
- **Trace-on limitations to fix or document before calling it exhaustive:** `DirEntry.is_dir` calls are not recorded (`io_helper.py:775,1038,1376,1800`), nor the `os.stat(file)` in macOS marker hiding (`:2233`). A `marker_read` line combines open/fstat/read, and a `read` line records the fingerprint size, not the bytes actually consumed by pandas (`:186-212`). Thus "every source operation" and "read bytes" overstate what the trace proves. `_entry_stat` calls `entry.is_symlink()` only while tracing (`:139-150`); that extra probe should be avoided or accounted for.
- **Share writes and Windows:** only `_trace` writes the trace file (`:56-69`), and normal source paths are only read except user-requested marker operations. But `HELAB_IO_TRACE` accepts any path, including a share, so "write nothing to the share" is guaranteed only when the operator chooses a local destination as the handoff instructs. `O_BINARY` is included for Windows; no native Windows runtime test was run here. Concurrent helper writes are a single `os.write` per line, but partial/interleaved lines on Windows are not ruled out; the handoff already acknowledges possible garbling. Failures opening/writing the trace are swallowed, so they should not fail the helper, but the trace may silently be incomplete.
- **Test limits:** `test_tracing_changes_no_event` compares event *kinds* only (`tests/test_io_trace.py:60-64,125-144`), not full event payloads or source-call parity. `test_the_gui_process_never_touches_source_folders` hooks Python calls only (`:198-249`). These are useful tests, not proof of every source operation or native GUI behavior.

## Checks rerun

- Full suite outside sandbox with `venv/bin` on PATH: `venv/bin/pytest -n 12 --reruns 5 --reruns-delay 1 --verbose --basetemp=.ai/temp/pytest-review`: **992 passed, 2 skipped, 2 xfailed in 26.53 s; no RERUN shown**.
- `mypy helab/ --strict`, `mypy tests --strict`, and each with `--platform win32`: **all pass** (77/58 source files). Initial sandbox runs failed because mypy could not open its SQLite cache; all four passed outside the sandbox.
- `pyright helab tests` and `pyright helab tests --pythonplatform Windows`: **0 errors, 0 warnings** each. Static Windows checks do not replace a native Windows trace run.
- `git diff --check 486cf56..HEAD`: **fails** on one extra blank line at EOF in each of `trace-session1.md:535` and `trace-session2.md:197`. No implementation files were changed in this review.

# Part 2 review at e3802af

Reviewed `36c2a12..e3802af` against the Part 1 constraints and the Part 2 handoff. The checkout had advanced to `6eb6a9c` when I ran the checks; that subsequent commit changes only a Windows trace test expectation. The implementation review below is for `e3802af`. **Verdict: two corrections are needed before this is ready for Live L3 integration.** The reported I/O reductions are plausible counts of HeLab calls on local APFS, not measured SMB packets or latency.

## Findings and protections

1. **roots_verify: pass.** `helab/utils/folder_cache.py:1475-1499,1876-1924` records the mount table requested by a listing in `_verify_asked`; completion itself does not ask again merely because the OS table differs. A newer listing during a running verification sets `_markers_again` for one follow-up. Failed checks wait for another listing. The volume IDs are handed from `volumes_verify` to `roots_verify`, avoiding the duplicate volume probe. The 5 s timer is a backstop, not a source of self-requeue.
2. **Load stats: pass.** `helab/io_helper.py:1482-1508` gets the fingerprint from the load's own `scandir` entries. The per-file before/after-read comparisons remain at `:1681-1697`; the final verify is retained, and the extra cache-save verify is conditional on a read after that verify (`:1724-1783`). The status adoption path avoids a second leaf listing without replacing a required integrity check.
3. **Half-written load: correction required.** `helab/io_helper.py:1665-1675` drops a recent file only when its bytes lack a final newline, whereas Live's `_whole_last_row` at `:1973-1982` also requires three nonempty fields. A local repro with `d_txy_forc3.txt` aged 8 s containing `3,2,3\n3,4,\n` yielded a `shot` event for 3 and `loaded(files=1, unsettled_files=0, problematic=[3])`. The incomplete final row is dropped by pandas, but the earlier row is shown and can enter the dataset cache. Apply the whole-row check to recent ordinary loads too; retain the before/after stats and mark that shot unsettled. The test at `tests/test_io_trace.py:443-474` covers only a missing newline. A complete-looking final row can still be a paused writer; the producer's temp-name/rename contract remains the durable fix.
4. **RAM-only quick check: pass within filesystem metadata limits.** `helab/io_helper.py:1353-1391,1467-1476` requires the held fingerprint, non-unsettled snapshot, matching location and known root marker, a folder mtime no newer than the snapshot, and sampled held shots. `full_check` bypasses it. Missing or changed files on an ordinary filesystem change force the full listing; the same folder-mtime and sampling limitations as the disk quick check remain. `helab/utils/folder_cache.py:1048-1055` sends the needed metadata.
5. **Live checks: pass for the stated protection.** `helab/io_helper.py:1833-1865,2047-2098` stats pending names without listing only while the folder remains safe and unchanged; it lists when a file is ready, changed, or missing. Every listing reads the marker at the known root and revalidates identity before held shots are reused, so a different marker/remount stops Live on that listing. The pending-only path does not assert identity until its next listing, but it reads no new shot meanwhile.
6. **Dedicated Live save: pass for nonempty datasets, with the empty-start gap below.** `helab/io_helper.py:1880-1970` lists once and checks identity, every held file's metadata, missing/changed shots and extra unsettled files; it reads the arrays from the helper's private `.npy` files and never opens a TXY for data. `helab/utils/folder_cache.py:1056-1074` supplies held arrays; the save uses a load guard and the shared `_write_dataset` budget, preference and pending-save path. The existing background lane, save serialization and quit wait remain. The guard is taken before save in the helper, not bypassed.
7. **RAM-held leaf selection: pass.** `helab/views/FolderExplorer.py:627-643,1349-1358` lets the load replace the redundant tree listing, and `helab/utils/folder_cache.py:1257-1268` adopts its checked summary. The test at `tests/test_io_trace.py:772-822` covers this path.
8. **Live L3 dependency: correction required.** `helab/io_helper.py:2018-2021` still raises `ValueError("Live needs the folder's loaded data — Retry")` for `memory=[]`; a direct call reproduced that exception. Empty datasets also cannot be saved: `helab/views/FolderExplorer.py:1534-1538` skips without `unsaved`, `helab/utils/folder_cache.py:1056-1065` falls back from `save_memory` when no base data exists, and `helab/io_helper.py:1941` requires `bool(data)` to save. Nonempty growing saves are exercised at `tests/test_io_trace.py:666-770` and pass. L3 can grow an initially empty Live folder only after these empty-start and empty-save paths are supported deliberately.

**I/O rules:** I found no regression in foreground/background/local lane assignment, cooperative pause/resume, slot ownership until helper exit, per-file retry boundaries, or mismatch handling. The new `save_held` stays a background `load` job; `helab/utils/io_service.py:224-240,356-395,718-739,765-890` retains the queue and exit accounting. These are source/test conclusions, not a native SMB stress run.

**Trace:** The Part 1 caveats are substantially addressed: `helab/io_helper.py:47-210` gates all trace work when off, separates marker open/fstat/read, records actual read bytes and `is_dir` checks without an extra symlink probe; `tests/test_io_trace.py` now compares full events and Python-visible calls. The trace destination rejects recognized network mounts and UNC paths, and no trace code writes into source folders. One caveat remains: `_trace_file` classifies the supplied path lexically via the mount table. A local symlink resolving onto an SMB share, or an unrecognized mount type, could still put the trace on the share; resolve the destination and fail closed if the no-share guarantee is strict. Windows was checked statically and by tests, not run natively; concurrent writes may still garble JSONL, as the handoff notes.

**SMB research:** The handoff cites seven sources. Microsoft oplock documentation [1] supports the narrow statement that metadata-only opens do not break an oplock; it does not prove that `stat` has no writer impact or no network latency. Apple SMBClient source [2,4] supports the compound metadata query, share-access and attribute-cache mechanics, but the `main` branch is not pinned to a macOS release or a Python `os.stat` packet capture. Microsoft server tuning [5] supports the listed Windows cache *defaults*, not a guarantee every lookup is stale for that duration. The archived Microsoft lease blog [3] was inaccessible in this review; the [SMB2 lease specification](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-smb2/4f35576a-6f3b-40f0-a832-1c30b0afccb3) is a stronger primary citation for flushing cached writes on lease change. `_sopen` documentation [6] supports permissive read/write sharing, while the ReactOS UCRT mirror [7] is secondary evidence for the exact Windows share mask. Qualify “stats don't disturb the writer,” “a data open does,” “never blocks the writer,” and “speed, not correctness”: those outcomes depend on lease, sharing mode, server and client. The handoff correctly identifies temp-name/rename as the producer-side completion protocol. No SMB packet capture or native Windows run was made here.

## Checks rerun

- Full suite **outside the sandbox**, `venv/bin` on PATH, `--basetemp=.ai/temp/pytest-review`, `-n 12 --reruns 5 --reruns-delay 1 --verbose`: **1010 passed, 2 skipped, 2 xfailed in 27.11 s; no RERUN shown**.
- `mypy helab/ --strict` and `mypy tests --strict`, both again with `--platform win32`: **all pass** (77 and 58 source files respectively).
- `pyright helab tests` and `pyright helab tests --pythonplatform Windows`: **0 errors, 0 warnings** each.
- `git diff --check 486cf56..HEAD`: **pass** at `6eb6a9c`. `e3802af..HEAD` changes only the Windows trace test expectation. No implementation files were edited in this review.

# Round 3 review at 49c1132 (Claude)

Reviewed `515bb22..49c1132` (47d9def, 9773b8a, 49c1132) against Tony's round 3 decisions, then a short pass over `486cf56..HEAD` against the AGENTS.md I/O rules. Codex's recheck on 515bb22 was stopped, so this replaces it. **Verdict: no blocker.** Both decisions are implemented as specified. The findings below are documentation, a quit-time wording gap and Windows caveats.

## 1. Settle age only (47d9def): pass

- `_whole_last_row`, `RECENT_SECONDS` and `_recent` are gone, and so are Live's tail and whole-row checks (`helab/io_helper.py`; no references are left in `helab/` or `tests/`). `_read_txy_file` returns only the frame (`:232`). `read_txy` in `_load` (`:1643-1650`) and Live's read (`:2133-2140`) no longer judge content.
- Kept as Tony asked: `SETTLE_SECONDS` (`:26-32`, now documenting the decision), Live's metadata-only `seen` rule, the before- and after-read stats in loads (`:1664-1668`) and Live, and Live's single data open per new file.
- The cache-save reread (`:1742-1752`) no longer raises "still being written". Its other failure paths are unchanged.
- Tests: `test_a_writer_stalled_longer_than_the_settle_age_is_read_as_it_is` (`tests/test_io_trace.py`) documents the accepted stall: shot 3 is shown as problematic with no unsettled count, and the finished file is read again as `modified_loaded`. `test_a_file_ending_mid_row_is_read_once_unchanged_a_check_apart` (`tests/test_live_check.py`) documents Live reading it after two unchanged looks. `test_loader_preserves_shots_and_drops_nan_rows` is back to a fresh file. I found no regression in other load or Live paths. The Live identity, sample, pending-only stats and `save_held` are untouched by this commit.

## 2. Trace as a per-session toggle (9773b8a): pass

- Help › Record I/O trace (this session) is checkable and unchecked at every start, and nothing saves it (`helab/views/HelabMainWindow.py:503-516`). The file is always `<DIR_TEMPS>/io-traces/io-trace-<YYYYmmdd-HHMMSS>[-n].jsonl` (`helab/utils/io_service.py:189-202`). `trace` (with `file`) is set at each attempt's start (`:400-403`) and sent in the payload (`:692-693`). The helper takes the file from its request (`io_helper._start_trace`, `:77-93`) and leaves `file` off each line.
- The terminal gets exactly the two INFO lines (`io_service.py:201,206`; main.py's coloredlogs is at DEBUG, so INFO prints). Helpers' stderr goes to DEVNULL, and a failed trace write is silent, so nothing else prints.
- Earlier traces: the question appears only when `earlier_io_traces` finds `io-trace-*.jsonl` (`HelabMainWindow.py:535-541`). Keep is the default and the reject role, so Esc or closing the box keeps them. Delete removes only the listed earlier files, before the new name is chosen, so never the new file. Nothing is deleted otherwise. All of this is covered by tests (`tests/test_helabMainWindow.py:359-449`).
- `HELAB_TEST_IO_TRACE` is the only environment switch, read by helpers only. The old `HELAB_IO_TRACE` does nothing (`tests/test_io_trace.py:87-99`), and `io_service` no longer imports `io_helper`.
- Temp-folder refusal: confirmed that only the cache folder is checked at startup (`constants.py:360-401`). The switch checks `DIR_TEMPS` with `cache_location_problem` (`io_service.py:75-82`), unticks, and warns. The handoff's proposal to refuse it at startup in `constants.py` is reasonable.
- Thread safety: `io_helper` starts no threads, so each helper process has one writer. Each line is one `os.write` on an `O_APPEND` descriptor. On local APFS, ext4 or NTFS under POSIX semantics, that append is atomic in practice. On Windows, see finding C.

## 3. Ownership: pass

Round 3's `data_roots.py` change is the one docstring line. In `HelabMainWindow.py` the changes are the imports, the status-bar label, the `ask_delete_old_traces` hook, the two Help items and `_toggle_io_trace`, `_ask_delete_old_traces` and `_show_io_trace_folder`. No plot-dock, settings-panel or script code is touched. The other code changes are in owned files (`io_helper.py`, `io_service.py`) and tests.

## Findings (most severe first; none blocking)

A. **Docs still describe the removed whole-row check.** `AGENTS.md:141` (Live) says a new file is read only when "… ending with a whole row (`_txy_complete`); a writer paused exactly at a row's end can still look finished". `roadmaps/live-monitoring.md:108-110` says the same. The handoff's proposed doc changes don't cover either. Add both: settle age plus `seen` only, by Tony's decision, with the converter's temp-name rename as the real fix. Live L3 may also edit AGENTS.md:141, so whoever lands second merges the wording.

B. **Quitting with the trace on prints no "I/O trace off" line.** `stop_io_trace` is called only from the menu toggle (`HelabMainWindow.py:526`). Neither `IOService.shutdown` nor the window's close path calls it. The handoff recipe (§7) says "untick it (or quit HeLab): the terminal prints `I/O trace off: <path>`". Fix: call `stop_io_trace()` from `IOService.shutdown` (an owned file), or correct the recipe.

C. **Windows: concurrent helpers can lose trace lines, not just garble them.** The MSVC CRT emulates `O_APPEND` with a seek to the end followed by `WriteFile`, so two helpers can write at the same offset and one line overwrites the other. The handoff ("the summary skips a garbled one") understates this: counts from a Windows trace can be silently low. Fix options: a per-helper file in a per-recording folder (`io-trace-<stamp>/<pid>.jsonl`, merged by `trace_summary.py`), or a `msvcrt.locking` byte lock around each write. At minimum, state it in the recipe for the Windows lab PCs. A related Windows nit: Delete old traces can't remove a file a still-running helper holds open (the CRT opens without `FILE_SHARE_DELETE`). The `OSError` is suppressed, so the file is silently kept.

D. **"Off" isn't immediate, and the new name isn't reserved.** A helper started while the trace was on keeps appending until it exits, which can be a long load or a save, after "I/O trace off" has printed. Also, `start_io_trace` checks only `os.path.exists`, and helpers create the file lazily. Suppose the trace goes on, then off, then on again within one second while a helper from the first recording hasn't written yet. The second recording can then get the same name and share the file. This is rare. Fix: create the file with `O_CREAT|O_EXCL` in `start_io_trace`, and note the lag in the tooltip or the recipe.

E. **Live after a stall longer than the settle age (information for Tony; documented in the handoff, not pinned by a test).** The partial shot is held as problematic. When the writer finishes, the next listing's sample (which usually includes the newest shot) or the next `save_held` (which checks every held file, `io_helper.py:1862,1897`) sees the shot as changed. `shots_missing` (`changed`) then stops Live and lists the folder as mismatched. That counts toward the 2/4/8 mismatch hold. So a slow converter shows up as a mismatch prompt rather than corrected data. It is accepted by design, but the Live test's docstring could say what follows, or a test could pin it.

F. **GUI-thread nit.** Switching the trace on calls `realpath` and `psutil.disk_partitions(all=True)` on the GUI thread (`io_trace_problem`). On Windows with a disconnected mapped drive, this can stall briefly. The same check already runs at startup (`constants.py`), so this is no new class of risk, and it happens on a deliberate menu action.

## Whole-branch sanity pass (486cf56..HEAD)

Lanes: `save_held` stays a background `load`, Live checks stay foreground, and `volumes_verify` and `roots_verify` stay in local and background lanes as before. `_before_start` changes only `roots_verify`'s payload. Pausing: `Pause.checkpoint` is unchanged in loads and `save_held`. Slots: `IORequest.arrays` are written in `_run` on the daemon thread. An early `return` on cancel still goes through `finally`, which confirms exit before `release`. Retries and requeues carry `arrays` and get a fresh `trace` at each attempt. Mismatch: `shots_missing` is unchanged in loads and is added for `save_held`. Cache first: the RAM quick check (`memory_check`) is skipped for `full_check`. The verify loop only re-asks for a new listing observation. I found no regression. Codex's Part 2 conclusions stand.

## Live L3 (agent/live-l3, incl. 672a96b)

`git merge-tree` of HEAD with `agent/live-l3` (and with 672a96b alone) shows **no textual conflicts**. Merged, `live_check` has L3's `if memory is None:` guard, and no content check remains to interact with an empty start. I ran the full suite on that merged tree, unpacked with `git archive` into a scratch folder: 1170 passed, 2 skipped, 2 xfailed, 3 failed. The 3 failures are git-provenance tests (`test_versioning.py` ×2, `test_release_recovery.py` ×1) that need a `.git`, which a `git archive` copy lacks. All Live, I/O-trace and folder tests passed, including L3's empty-start and Live-off-save tests. One expected doc merge is AGENTS.md:141 (A).

## Checks rerun (floor root, venv and floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **1014 passed, 2 skipped, 2 xfailed, 1 rerun**. The `-q` output didn't name the rerun test. Two more identical runs with `-rR` were **clean (1014 passed, no RERUN)**.
- `mypy helab/ --strict` (77 files), `mypy tests --strict` (58), both also with `--platform win32`: **no issues**.
- `pyright helab tests` and with `--pythonplatform Windows`: **0 errors, 0 warnings**.
- `git diff --check 486cf56..HEAD`: **clean**.
- Not run: native Windows. The Windows points (C, F) come from reading the code and CRT behaviour.

# Recheck at 660ba9c (Claude)

Reviewed `49c1132..660ba9c`: the round 3 fixes (e66003a B, 97e2f02 C, 118e0f0 D, 14005be F), the dev merge (02c88dc), E (f79ec8e, Tony's decision) and 660ba9c. **Verdict: one correctness bug in E's save path to fix before landing, and one flaky new test.** The merge, the trace pieces and E's Live-check path pass.

## Findings (most severe first)

1. **E: a Live save that reads a shot again is cancelled, and that cancel stops the save.** (`helab/io_helper.py` `save_held`, `helab/utils/folder_cache.py:2251-2259`.) How it happens:
   - When `save_held` reads a recent changed shot again, its `loaded` carries a new `signature`.
   - It sends no `scan_summary`, so the folder's snapshot still has the signature of the Live check that read the shot unfinished.
   - FolderCache drops any `load` whose signature differs from the snapshot's: `_cancel_job` calls `service.cancel`, which stops the helper. The helper writes the disk cache only after `loaded` (`disk_cache_pending`), so that write is lost or cut short.
   - The tab gets `cancelled`, so no WARNING and no note appear, and RAM keeps the unfinished shot.

   **Repro** (scratch copy of HEAD, the `tests/test_live.py` harness, the save run through the real `save_held` with the request's `arrays` and `recent`):
   - Live reads shot 3 mid-row.
   - The writer finishes and the folder is aged.
   - `stop_live()` runs before another check, and the save is run.
   - Result: `save_held` sends `shot, load_source, loaded(live_reread=[3]), cache_saved, disk_cached`. FolderCache's `_cancel_job` fires for the folder, the only dataset kept is the old one, and the tab still shows shot 3 as `[[3,2,3]]`.
   - In production the helper would be stopped rather than finish its write. My replay ran it to the end, so here the disk got the whole shot while RAM kept the partial one.

   This hits the saves at Live off, another folder, tab switch or close, and quit: any save where the save, not a check, is the first to read the shot again. An autosave while Live is on usually follows a listing check that already read it.

   **Test gap:** `tests/test_live.py`'s `replay` runs an ordinary `load` for saves and never `save_held`. The only `save_held` re-read test is at helper level (`tests/test_io_trace.py:736`), which doesn't go through FolderCache.

   **Fix direction:** have `save_held` send a `scan_summary` with its new fingerprint before `loaded`, adopted as Live's summaries are. Or exempt `save_memory` jobs from the snapshot-signature check. Then add a tab-level test that runs saves through `save_held`.

2. **Flaky new test: `tests/test_helabMainWindow.py::test_help_menu_records_the_io_trace_for_this_session`.**
   - It needed a RERUN in the official run, and it failed both of my no-rerun runs (`-n 6 -x`).
   - Failure: `asked == [(1, 1664, …)]` instead of `[(1, 6, …)]` at `:411`.
   - Cause: the `main_window` fixture's own startup helpers (listing, volume checks) are traced into the first recording while it's on. The test assumes only its own 6 bytes are there. The trace works correctly; the test assumes an idle app.
   - Fix: compute the expected size from the files actually in the recording, or wait for the service to go idle before turning the trace on.

3. **E, information for Tony (by design, worth stating in the AGENTS.md wording):**
   - Within the 5-minute window, a held recent shot is guarded only by the missing-file and identity checks, which run first (`io_helper.py:2126-2134`), not by the sample.
   - A Live session started from an empty folder (L3) has every held shot recent for its first 5 minutes.
   - So a copy of the same data root swapped in at the same path within that window would be read again rather than flagged. Older shots in the sample still catch a remount or copy.

4. **Docs:**
   - The handoff now proposes the AGENTS.md Live wording, which fixes my round 3 point A for AGENTS.md. `roadmaps/live-monitoring.md:108-110` ("ending with a whole row") is still not on the proposal list.
   - AGENTS.md's local-lane paragraph should name `trace_check`.
   - `compare_traces.py` on traces without phase lines prints an empty table. That predates this change; a whole-trace row would help Tony's real-share comparison.

## 1. The merge (02c88dc): pass

- L3's pieces are all at HEAD: the `if memory is None` guard (`io_helper.py:2057`), `FolderCache.empty_dataset` (`folder_cache.py:797`), the "waiting for the first shot" state (`FolderExplorer.py:1793`, `HelabMainWindow.py:1366`) and plot following (`helab/analysis/follow.py`).
- `git diff 9f6ee5a 02c88dc` changes only this branch's files.
- The Live tests from both sides run in the full suite: `test_live.py`, `test_live_check.py`, `test_live_io.py`, `test_live_plots.py` and `test_io_trace.py`'s Live tests.

## 2. E's rules

- **Per shot, and reset on a re-read:**
  - `read_at` is set when a check delivers new shots (`FolderExplorer.py:1694-1696`).
  - It is reset to now in `_live_reread` when a shot is read again.
  - It is pruned at 5 minutes when the request is built (`_live_recent`).
  - The initial load's shots never enter it.
  - On the save path, the reset never happens because of finding 1.
- **Identity first:** pass. In `live_check`, missing shots, then identity (`root`), then the sample run before any re-read. A changed shot that isn't recent stops the check before re-reads are considered (`:2136-2158`). `save_held` checks identity before `changed` as well.
- **Older shots:** pass. `shots_missing changed` for a held shot that isn't recent, and `missing` and `root`, are unchanged. The tab test pins a shot older than the window stopping Live as mismatched.
- **No extra I/O in the steady state:** pass. The sample adds only held shots the previous check saw changed (`previous & held`). Re-reads cost a stat before, one read and a stat after, only for changed recent shots. The pending-only path is unchanged.

## 3. Trace pieces

- **B, quitting:** pass. `IOService.shutdown` logs "I/O trace off".
- **C, one file per helper:** pass.
  - Each helper writes its own `<recording>/<pid>.jsonl`, so there is one writer per file, which also fixes the Windows CRT append race.
  - If Windows reuses a PID, the file is appended after the earlier helper has exited.
  - Delete removes the listed files, then `rmdir`s each emptied folder. It reports files Windows refuses to delete and keeps them.
  - Nit: a file a still-running helper of that recording creates after the check stops the `rmdir`, so that folder is kept without a message. Harmless.
- **D, reserved name:** pass. `_new_recording` uses an exclusive `os.mkdir` with `-2`, `-3`… suffixes.
- **F, the temp-folder check:** pass.
  - `trace_check` runs on the local lane with a 10 s no-progress timeout. It reads only the temp folder and the mount table, and isn't traced.
  - The window keeps an owner and a generation. Unticking cancels the request, and late or stale answers are dropped (`_on_trace_check`).
  - An error or timeout refuses with a warning. Unticking while asked is honoured.
  - The GUI thread only deletes and makes folders, all in the temp folder.
  - A stalled check holds one of the 2 local slots until its helper exits.
- **Summary scripts:** pass. I ran a two-helper recording folder through `trace_summary.py` and `compare_traces.py`: both read every `*.jsonl` and merge them in time order.

## 4. AGENTS.md I/O rules across the whole branch (486cf56..HEAD, after the merge)

- **Lanes:** unchanged apart from adding `trace_check` to the local lane. Live checks stay foreground, `save_held` stays a background `load`, and `volumes_verify` and `roots_verify` are as Codex passed them.
- **Pausing:** `Pause.checkpoint` is in `save_held`'s re-read loop and in `live_check`'s reads.
- **Slots until exit:** `_run`'s `finally` and `_reap` are unchanged.
- **Retries:** carry `arrays`, and get a fresh `trace` at each attempt.
- **Mismatch:** unchanged except for E's recent window.
- **Cache first:** unchanged.
- I found no regression apart from finding 1, which is a FolderCache interaction, not a lane or slot issue.

## Checks rerun (floor root, venv and floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: **1181 passed, 2 skipped, 2 xfailed, 1 rerun.** `RERUN tests/test_helabMainWindow.py::test_help_menu_records_the_io_trace_for_this_session` (finding 2). Two more runs without reruns (`-n 6 -x`) failed that test both times.
- `mypy helab/ --strict` (79 files) and `mypy tests --strict` (62), both also with `--platform win32`: **no issues**.
- `pyright helab tests`, also with `--pythonplatform Windows`: **0 errors, 0 warnings**.
- `git diff --check 486cf56..HEAD`: **clean**.
- Not run: native Windows. The repro for finding 1 lives in a scratch copy and touches nothing in the floor.

# Recheck at 65a15a2 (Claude)

Reviewed `660ba9c..65a15a2`: 3e0b59b (fix 1), a34707d (flaky test), d6d6d24 (Windows line endings), c872478 (doc proposals, unphased `compare_traces`) and 65a15a2. **Verdict: no blocker. Fix 1 fixes my repro.** One narrow race remains in the save's summary adoption (finding 1). It is worth a small fix, but it is short-lived and self-correcting.

## Fix 1 (3e0b59b)

- **My repro, rerun unchanged on a scratch copy of HEAD** (files written as bytes): `save_held` sends `shot, scan_summary, load_source, loaded, cache_saved, disk_cached`. `_cancel_job` doesn't fire, and FolderCache keeps the new dataset `[1, 2, 3]`. **Fixed.** The worker's tab test `test_the_save_at_live_off_reads_a_recently_read_shot_again_and_saves_it` (`tests/test_live.py`) pins the same sequence: the shown data, the dataset, the snapshot's signature, the disk cache, the note after the session ends, and the WARNING.
- **Can it hide a real mismatch? No.** `save_held` sends the summary only after the missing-file, identity (`root`) and stale-changed (`changed`, not recent) checks have passed; each of those `return`s first. It sends it only when a shot was replaced (`if replaced:`). An unsettled recent shot isn't replaced, so it keeps the held fingerprint and sends no summary.
- **Saves with nothing re-read: unchanged in events and outcome.** `test_io_trace.py` now asserts the plain save sends no `scan_summary`, and the rest of that test's assertions are unchanged. One small I/O difference: the listing loop now also calls `_is_dir` on entries that aren't TXY or raw files, until it finds a subfolder (`io_helper.py:1906-1915`). That happens on every save, not only re-reads. It is usually free (d_type on macOS and Windows) and is traced as `is_dir`, but it isn't strictly "unchanged". Gating the subfolder check on a re-read would need the listing to be redone. This is a nit, acceptable as is.
- **Did the replay change weaken a test? No.** `replay` now runs a request with `save_memory` and `arrays` through the real `save_held`, as `IOService._run` would. Requests without arrays (FolderCache's fallback when no base data is held) still run the ordinary `load`. The existing Live save tests keep their assertions and now exercise the production save path, which makes them stronger. The only edited assertion is the note-expiry line, adapted to `_reread_notes`.
- **The note per folder** (`FolderExplorer._reread_notes`) is pruned when read after its minute. The summary's third line shows it after Live stops. Fine.

## Findings

1. **Adopting a save's summary as Live's can overwrite a newer listing and mark it freshly checked.** (`folder_cache.py:2231-2233`, then `_adopt_load_summary`'s `live` branch at `:1255-1259`, which has no ordering guard.)
   - **Probe** (scratch copy of HEAD):
     - Run `save_held`, which lists at t0 and reads shot 3 again.
     - Meanwhile shot 4 arrives, and the snapshot takes a newer listing (txy `[1,2,3,4]`, newer `scanned_at`, a details signature).
     - Then deliver the save's events.
   - **Result:** the snapshot goes back to txy `[1, 2, 3]` with the save's older `scanned_at`, and `checked_at` is now. The `loaded` signature then matches, so the save is kept and its data counts as checked.
   - **When:** after Live off the tree is unlocked, and a Refresh listing runs in the foreground while the save runs in the background. A second tab browsing the folder is another way in. The window is the save's listing plus its re-read, about a second.
   - **Effect:** for `FRESH_SECONDS` the tree's counts and the folder's "checked" state miss shot 4. The next check or selection relists the folder. No data is lost.
   - Before fix 1, the newer signature would have cancelled this save instead. That was worse.
   - **Fix:** for `save_memory` jobs, adopt only when the summary's `scanned_at` isn't older than the snapshot's, as the non-live branch at `:1265-1266` does. When it is older, let the save through without the signature check rather than cancel it. (Live checks have the same unguarded adoption, but while Live is on the tab's tree is locked; only another tab could race it.)

2. **Rerun in an untouched test:** `tests/test_two_step_browse.py::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks` (RERUN, then PASSED, in the official run below). This branch doesn't change that test file. Three more full runs without reruns (`-n 6`) were clean. The worker reports it's comparing it with the base. I have no evidence it's a regression.

## Other commits

- **a34707d:** the trace-menu test waits for the service to go idle after each recording is turned off, and expects the actual files' size. It stays strict about which recordings are listed, kept and deleted. It passed all my runs, including 3 without reruns.
- **d6d6d24:** the size-sensitive files are written as bytes, or with `newline="\n"`. That matches the RSPE failures, and the production code is unchanged.
- **c872478:** traces without phase lines give one "whole trace" row (seconds up to the last line). It adds the proposed wording for `roadmaps/live-monitoring.md:108-110` and the AGENTS.md local-lane `trace_check` wording. Both close my earlier doc points.

## Checks rerun (floor root, venv and floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: **1182 passed, 2 skipped, 2 xfailed, 1 rerun** (finding 2). Three more runs with `-n 6` and no reruns: **1182 passed each**.
- `mypy helab/ --strict` (79 files) and `mypy tests --strict` (62), both also with `--platform win32`: **no issues**.
- `pyright helab tests`, also with `--pythonplatform Windows`: **0 errors, 0 warnings**.
- `git diff --check 486cf56..HEAD`: **clean**.
- Not run: native Windows. The probes live in a scratch copy and touch nothing in the floor.
