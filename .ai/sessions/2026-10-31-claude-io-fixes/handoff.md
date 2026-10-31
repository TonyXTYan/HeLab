# Handoff: I/O fixes (`agent/io-fixes`)

Worker: Conduit (Claude Code, Opus 5.5), 2026-10-31. Brief: [brief.md](brief.md). Base `0571ff2` (brief commit
`3e13616`). Findings: the area review's `io.md` (`git show 573361f:.ai/sessions/2026-10-31-claude-area-review/io.md`).
Area `io`; no file outside the owned paths changed (`cache_store.py` untouched; io-5 was done in `loading.py`).
`dev/v0.0.8` not merged yet: waiting for CoCo's word, as the brief says.

## What changed (one commit each, every fix with a test that fails before it)

| Item | Commit | Change | Test |
|---|---|---|---|
| io-1 | `82d84b2` | `IOService.mismatch_spared`: the hold never holds, pauses or cancels a save (`payload.save`, Live's too) or a Live check (`payload.live`). `cancel_operations` became `cancel_held` (its only caller), which spares them. `FolderCache.cancel_for_quit` lifts the hold. | `test_mismatched_folders.py`: `test_the_hold_spares_saves_and_live_checks`, `test_quitting_lifts_the_hold` |
| io-2 | `2225d90` | `SharedJob.choice` + one `job_key()` for filing and forgetting, so a plot's `load:<choice>` job is forgotten when it ends (no dead job to join, no arrays kept outside the budget). `_invalidate_data` cancels every load and cached read of the path, choice loads included. | new `tests/test_folder_cache_jobs.py` (3 tests) |
| io-3 | `1119339`, `64cb2ce` | `save_held` always sends its `scan_summary` (it used to only after reading shots again). The existing `scanned_at` rule then adopts it when the save's listing is newer, else keeps the newer status (`behind_listing`) and the data unchecked. Cost: one folder stat per save (`summary._summary`); `test_io_trace` updated for it. | `test_live.py`: `test_a_live_save_after_a_newer_listing_isnt_cancelled`, `test_a_live_save_overtaken_by_a_listing_isnt_cancelled` |
| io-4 | `dd02aff` | In `save_held`, a held shot with no array (unreadable when read, kept known) is no mismatch, as in a Live check: changed, it is read again once settled (saved as held and counted unsettled until then); gone, it is dropped. | `test_live_check.py`: three `test_a_save_…unreadable…` tests |
| io-5 | `3f9924d` | `loading.load` counts the cache whole only if the saved signature also equals the folder's now (both the decision to read the dataset and `whole`). Otherwise it reuses every cached shot, reads no TXY file, and saves the dataset with the new signature. | `test_txy_sources.py`: `test_a_load_finding_the_cache_whole_with_a_new_signature_saves_it` |
| A39.2 | `10a9c3c`, `f945f69` | `live_check`: a held shot kept on MATLAB's TXY by the held-kind rule, which the source would take from HeLab's now, is read again from HeLab's TXY like a changed shot (`helab_rereads`), once settled and seen unchanged a check apart. Until then its MATLAB TXY still feeds the mismatch rule, so `fefe6ab`'s no-mismatch guarantee holds. Re-reads caused by a new HeLab TXY (this switch, and a HeLab-held shot converted again) are marked `converted` in `live_reread`; `explorer_live._live_reread` logs them as INFO with no Live-line note. | `test_txy_sources.py`: `test_live_takes_helabs_txy_for_a_shot_held_from_matlabs`; `test_live.py`: `test_a_shot_read_again_from_helabs_txy_converted_since_is_no_warning` |
| io-6 | `4515113` | `_foreground_busy` skips requests `held_by_mismatch`, so a paused selected load doesn't hold icons, listings, roots_verify or auto-convert. | `test_mismatched_folders.py`: `test_a_foreground_load_the_hold_paused_doesnt_hold_background_work` |
| io-7 | `dd3efd7` | `_evict` spares datasets of folders a check awaits (`_awaiting_producers`) until `_resume_awaiting`. | `test_folder_cache_jobs.py`: `test_a_background_check_keeps_its_cached_reads_dataset_over_the_ram_budget` |
| io-8 | `f2727a5` | `pause_requested` changes only once the flag is as asked (`_write_pause` returns it; a flag already gone counts as removed), so a failed write is retried next tick. The start-up write in `_run` clears `pause_requested` when it fails. | `test_io_lanes.py`: `test_a_pause_flag_that_couldnt_be_removed_is_removed_on_a_later_tick` |

## The four unverified notes

1. **`_invalidate_data` silent on queued deliveries: real, fixed** (`8f035ce`). A tab's load waiting for another
   (here the running load of the choice before a Settings change) heard `queued` and then nothing after a clear.
   It now emits `cancelled` and drops the delivery, as `_mismatch` does. Test:
   `test_clearing_a_folders_cache_tells_a_waiting_load_it_was_cancelled`.
2. **Helpers outliving HeLab: real, fixed for running helpers** (`e15d809`). `shutdown()` now kills every retired
   helper still running itself. `Popen.kill` and `poll` never wait, and the reapers still confirm exits. Test:
   `test_shutdown_stops_its_helpers_itself_not_only_from_the_reapers`, which holds the reapers back. **Left
   over:** a helper still being started in `_run` at that moment (no `process` yet) is only stopped by `_run`'s
   daemon thread. It ends at its first stdout write to the closed pipe (proposed A~1).
3. **`error` then synthetic `done`: harmless, no change** (`ad15d62`). The `error` ends and forgets the job. The
   late `done` carries only the producer's id, which no tab listens to (every `resultReady` listener filters by
   owner), and it never reaches a newer job of the folder. Test: `test_a_late_done_after_an_error_reaches_no_tab`.
4. **A save putting off the minute listing: real, fixed** (`ad90e34`). `_live_loaded` now moves `listed_at`
   only for a check's listing (`live_listed`). Test: `test_a_live_save_doesnt_put_off_lives_minute_listing`.

The review's unverified sub-points are covered too:
- io-3's "one tab's own background details": the fix doesn't depend on which listing moved the snapshot.
- io-5's GUI effect: the cache now gets the new signature, so a cached read answers with it.

The review's scratch reproductions pass on this tree. Two exceptions, both from the scratch files themselves, not the code:
- `test_scratch_save_held.py` gives `save_held` an `output` folder it never creates; the save now writes shot 2's
  artifact there. In the app the helper's folder always exists.
- `check_hold.py` calls the removed `cancel_operations`.

## Checks

**Final run, at `c843b15`** (`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-full`):
**8534 passed, 672 skipped, 2 warnings, no RERUN** (no "rerun reasons" section). Type checks all clean:
- `mypy helab/ --strict`, `mypy helab/`, `mypy tests --strict`, `mypy tests`: no issues.
- `mypy helab/ --strict --platform win32`: no issues.
- `pyright helab tests` and `pyright --pythonplatform Windows helab tests`: 0 errors.

A second full run at `ad90e34` found one type error in the note-2 test (`Popen[bytes]` for `Popen[str]`): 3
`test_typing` failures, 15 RERUN, all of them those three tests (5 each). Fixed in `c843b15`.

A mid-point full run (at `10a9c3c`) found one mypy error in the A39.2 code: 4 failed, 8523 passed, 20 RERUN. All
20 reruns were those four `test_typing` tests failing on that one deterministic error (5 reruns each); no flaky
test. Fixed in `f945f69`.

## Proposed doc changes (for the Coordinator)

**`.ai/architecture/io-and-browsing.md`**, the cache-first paragraph:
- After "loads and scans pause and none start (`IOService.mismatch_hold`, `MISMATCH_HELD`; browsing, cached reads,
  cache saves and icons go on)", add: "saves (Live's too) and Live checks are spared (`IOService.mismatch_spared`):
  neither held, paused nor cancelled by Cancel all loads and scans (`cancel_held`); a load the hold pauses doesn't
  hold background work (`_foreground_busy`); quitting lifts the hold".
- At "A full listing that finds every cached TXY file unchanged … (`CacheStore.confirm_dataset`)", add: "and only
  when the cached signature is the folder's too; otherwise (a MATLAB TXY arrived or settled for a shot held from
  HeLab's) the dataset is saved again with no TXY read (io-5)".
- In the slots and pausing text: "a pause flag that can't be written is tried again on the next tick
  (`_apply_pauses`, io-8)"; "`shutdown` kills retired helpers itself as well as through the reapers".
- FolderCache jobs: "jobs are filed and forgotten by one `job_key(operation, path, live, choice)`, a plot's own
  choice as `load:<choice>`"; "a clear (`_invalidate_data`) cancels every load and cached read of the folder and
  tells waiting deliveries `cancelled`"; "the RAM budget spares a cached read's dataset its check waits for".

**`.ai/architecture/live.md`**, the Live section:
- "A Live save always sends its folder summary (`scan_summary`) before `loaded`; a newer listing elsewhere keeps
  its own status and the save's data isn't counted as checked (io-3)."
- "A save treats a held shot with no data (found unreadable) as a Live check does: read again once settled if it
  changed, dropped if gone, never a mismatch (io-4)."
- "Under HeLab priority, a shot held from MATLAB's TXY switches to HeLab's TXY converted during Live, read again
  like a changed shot; its MATLAB TXY feeds the mismatch rule until then (A39.2, Q38.2). A re-read caused by a new
  HeLab TXY is `converted` in `live_reread`: logged as INFO, no note on the Live line."
- "`listed_at` moves only for a check's listing, not a save's."

**`.ai/AI_TODO.md`**: A39.2 done (`10a9c3c`).

**`roadmaps/known-issues.md`**: nothing to add from this floor besides A~1, if the Coordinator files it there.

## Proposals (provisional IDs)

- **Q~1 (wording, Tony's).** `MissingShotsWindow.CANCEL_TIP` says "Cancel every load and scan, running, paused or
  queued". Since io-1, saves and Live checks are spared. Proposed: "Cancel every load and scan, running, paused or
  queued. Browsing, cached data, saves and Live go on; loads already saving their cached data finish." Not changed:
  the file is outside the owned paths, and the wording is Tony's.
- **A~1.** A helper still starting in `IOService._run` when HeLab quits (no `process` yet) is stopped only by
  `_run`'s daemon thread, so it may run until its first stdout write fails. Low risk. A fix: `_run` checks
  `self.closed` right after `Popen` and kills.
- **A~2.** In `live_check`, a switched or HeLab-held shot whose new HeLab TXY turns out unreadable drops the held
  data and keeps the shot known-unreadable. This was already so for HeLab-held shots converted again. HeLab writes
  TXY by temporary name and rename, so it is unlikely. Keeping the held data until a readable TXY is read would be
  safer.
- **M~1.** At the lab, with Live and auto-convert on under HeLab priority and MATLAB's converter also running, check:
  shots first read from MATLAB's TXY switch to HeLab's within two checks of their conversion; no "changed after it
  was read" note appears on the Live line; the log has one INFO line per switched shot.
