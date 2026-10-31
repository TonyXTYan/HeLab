# Review: I/O fixes (`agent/io-fixes`, `0571ff2..8aedf6d`)

Reviewer: Claude Code (Opus 5.5), 2026-10-31, read-only on code. Brief: [brief.md](brief.md); handoff:
[handoff.md](handoff.md); findings checked against the area review's `io.md` (`573361f`). I read the diff itself,
not only the handoff, against the I/O rules in `AGENTS.md` and `.ai/architecture/{io-and-browsing,live,cache-store,testing}.md`.

**Verdict: no blocker.** 2 findings (0 High, 0 Medium, 2 Low), plus 5 notes that don't count. Every fix does
what its finding asks. Every new test fails with its fix reverted. The suite and the type checks are clean.

## Findings

### IO-R1 · Low · Quitting lifts the hold before it cancels, so held loads and scans start helpers that are killed at once

**Where:** `helab/utils/folder_cache.py:2868-2869` (`cancel_for_quit`, io-1, `82d84b2`).

**Scenario:**
1. The hold is on, and an ordinary load and a scan wait in `IOService.pending`.
2. The user quits. `cancel_for_quit` calls `resume_after_mismatch()` first.
3. `set_mismatch_hold(False)` calls `reschedule()`, and `_dispatch()` starts the held load and scan
   (`_start` → `_run`, a helper process each, as far as the lanes have room).
4. The loop just below then cancels their jobs, so those helpers are killed as soon as they start.
5. Each one holds its slot until its exit is confirmed, so a save the quit window waits for can start later than
   it should. A paused held load loses its pause flag before it is cancelled.

There is no data risk: the store's save guards fence these helpers. But the quit does work it doesn't need, and
the docstring promises that "none of those start again".

**Verified:**
- Scratch `.ai/temp/io-fixes-review/test_quit_hold_order.py`: with the hold on, a `cache.submit` load and scan
  pending, and `_run` recorded, `cancel_for_quit()` starts `['/plain', '/scan']`. The test fails.
- Moving `self.resume_after_mismatch()` to the end of `cancel_for_quit`, after the cancel loop, makes it pass. I
  tried this in a scratch copy of the tree only, together with `test_mismatched_folders.py` and
  `test_quit_confirms.py` (22 passed).
- `test_quitting_lifts_the_hold` (`tests/test_mismatched_folders.py:138`) only checks the flag, and its
  `frozen()` service stubs out `_dispatch`, so it can't see this.

**Fix:** lift the hold last in `cancel_for_quit`, and add an assertion to the test that nothing held was
started (`_run` recorded, `_dispatch` left real).

### IO-R2 · Low · `converted` marks every re-read of a HeLab-held shot, including one read again from MATLAB's TXY

**Where:** `helab/io_ops/live.py:238` (`converted = {item[0] for item in helab_rereads}`, A39.2, `10a9c3c`). The
log line it causes is at `helab/views/explorer_live.py:462`.

**Scenario:**
1. Under HeLab priority, a shot is held from HeLab's TXY.
2. That TXY is removed (for example, its converted TXY is cleared) while MATLAB's TXY is there.
3. `compose` now picks MATLAB's TXY (origin `""`), so `origin != held_origins[shot]` and the shot joins
   `helab_rereads` (`:234`). That is correct.
4. It is also put in `converted`, though nothing was converted. `_live_reread` then logs "read again from HeLab's
   TXY converted since: …/d_txy_forc2.txt" as INFO.

The log names the wrong cause, which matters because Tony reads these lines to report converter behaviour.
Before this branch the same case logged a WARNING and showed the Live-line "writer paused" note, which was also
wrong. So this is a matter of wording, not a regression in behaviour.

**Verified:**
- Scratch `.ai/temp/io-fixes-review/test_converted_label.py` (in `live_check`, using `test_txy_sources`' helpers):
  the `live_reread` entry for shot 2 has the path `run/d_txy_forc2.txt` and `converted: True`. The test fails.
- With `converted = {item[0] for item in helab_rereads if origins.get(item[0])}` (only shots whose new TXY is
  HeLab's), the test passes. So do `test_txy_sources.py`, `test_live.py` and `test_live_check.py` (109 passed).
  I tried this in the scratch copy only.

**Fix:** the one-line filter above, plus that scratch case as a test.

## Each fix against its finding

| Item | Matches the finding / rules | Test fails without the fix |
|---|---|---|
| io-1 `82d84b2` | Yes. `mismatch_spared` (`payload.save` or `live`) is used in `held_by_mismatch`, so `_dispatch` and `_apply_pauses` follow it, and in `cancel_held`. Quitting lifts the hold (see IO-R1 for the order). | 3/3 fail |
| io-2 `2225d90` | Yes. One `job_key()`; `SharedJob.choice`; `_invalidate_data` cancels every `load`/`cached` job of the path, choice jobs and saves included (saves were cancelled before too). | 3/3 fail |
| io-3 `1119339` | Yes. `save_held` always sends `scan_summary`; the existing `scanned_at` rule adopts it or sets `behind_listing`. Costs one folder stat per save. | 2/2 fail |
| io-4 `dd02aff` | Yes. A held shot with no `.npy` is `unread`: gone → dropped; changed and settled → read again; unsettled → held. It is never `stale`. | 3/3 new tests fail |
| io-5 `3f9924d` | Yes, in `loading.py` only (`cache_store.py` untouched). See note N1 for the cost. | 1/1 fails |
| A39.2 `10a9c3c`+`f945f69` | Yes. The switch happens only under a source that picks HeLab's; it waits for settle plus a check apart (`previous`); the MATLAB TXY feeds the mismatch sample until then; a switched shot not read this check keeps its MATLAB origin (`kept_origins`). See IO-R2. | 2/2 fail |
| io-6 `4515113` | Yes. `_foreground_busy` skips requests `held_by_mismatch`. | 1/1 fails |
| io-7 `dd3efd7` | Yes. It pins every dataset of a path in `_awaiting_producers`, cleared by `_resume_awaiting` whenever the cached job is forgotten, so the pin always ends. | 1/1 fails |
| io-8 `f2727a5` | Yes. `pause_requested` changes only once the flag write succeeds (under `request.control`); a failed write at start-up is retried on the next tick. | 1/1 fails |
| Note 1 `8f035ce` | Yes. Waiting and RAM deliveries are told `cancelled` and dropped, as `_mismatch` does. | 1/1 fails |
| Note 2 `e15d809` | Yes. Only `poll`/`kill` (no waits) on the GUI thread; slots are still freed only by the reapers' `exited` flag. | 1/1 fails |
| Note 3 `ad15d62` | Test only; I agree with the analysis. | n/a (no code) |
| Note 4 `ad90e34` | Yes. `listed_at` moves only for `live_listed`. | 1/1 fails |

**How "fails without the fix" was checked:** I extracted `8aedf6d` into `.ai/temp/rv-io/` with `git archive`
and imported it through `PYTHONPATH`. For each commit I reverse-applied its `helab/` diff with `patch -R`, ran
its new tests, then re-applied it. With every fix in, the baseline is 144 passed.

## Rules checked

- **Slots:** none freed on delivery. The kill in `shutdown` doesn't touch `_forget`.
- **The GUI thread never waits:** `shutdown` uses `poll`/`kill` only. Nothing new joins, sleeps or waits.
- **Queues stay bounded:** nothing new is queued without a bound.
- **Settle time:** io-4's re-reads and A39.2's switch both go through `_settled`, and the switch also needs the
  same stat a check apart.
- **Automatic scans:** none added outside `FolderCache.submit`.
- **Source folders:** nothing new is written to them; io-4's artifacts go to the helper's `output`.
- **Owned paths:** only owned paths changed.

## Notes (not counted)

- **N1 (io-5's cost).** A change to the signature alone now rewrites the whole cached dataset: the blob is read,
  decompressed, packed again and written through the disk budget (which can bring up the pending-save
  dialogs). If the dataset is too large to unpack, the save reads every held shot's TXY again. This happens once
  per change and is what the brief chose. Possible follow-up for the `cache` area: `confirm_dataset` takes the
  signature, and the load keeps `cached=True`.
- **N2.** I agree with A~1 and A~2. On A~2: a fresh load under HeLab priority would take the same unreadable
  HeLab TXY, so this matches the source rule rather than being a regression.
- **N3 (note 4).** A Live check that joins another tab's load gets a `loaded` without `live_listed`, so
  `listed_at` stays where it was and Live lists once more than it needs to. This is harmless.
- **N4.** I agree with Q~1: since io-1, `CANCEL_TIP` ("Cancel every load and scan…") is no longer accurate.
- **N5.** The proposed docs look right. Once IO-R1 is fixed, the io-and-browsing line should read "quitting
  lifts the hold after cancelling what it held".

## Checks run

- **Touched tests** (`test_folder_cache_jobs`, `test_io_lanes`, `test_io_service_run`, `test_io_trace`,
  `test_live`, `test_live_check`, `test_mismatched_folders`, `test_txy_sources`, `test_folder_cache`,
  `test_quit_confirms`), `-n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-probe`: **218 passed, no
  RERUN**.
- **Full suite** at `4457bae` (this range plus the merge of `dev/v0.0.8`),
  `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **8557 passed, 672 skipped, 2
  warnings, no RERUN** (no "rerun reasons" section).
- **Type checks:** no issues from `mypy helab/ --strict` (195 files), `mypy tests --strict` (177) or
  `mypy helab/ --strict --platform win32`. 0 errors from `pyright helab tests` and
  `pyright --pythonplatform Windows helab tests`.
- **Not rerun:** CI. The handoff's run 41159308171 is at `8aedf6d`, before the merge.
- While I was reviewing, the worker committed `8145ff1` (a Live-convert test from the merge, outside this
  range). I did not review it.

## Re-check of the fixes (`5457ccd..623ce20`, plus `8145ff1`)

Reviewer: Claude Code (Opus 5.5), 2026-10-31. I checked only the fix diff.

**Verdict: no open findings.** IO-R1 and IO-R2 are fixed.

- **IO-R1, fixed** (`af5a205`). `cancel_for_quit` now lifts the hold after its cancel loop, as proposed. The new
  test is `test_quitting_starts_none_of_the_loads_and_scans_the_hold_held`. It uses `held_service`, so the real
  `_dispatch` runs. It asserts that no held load or scan sends `started` and that nothing is active. It fails
  with `af5a205` reverted and passes with it.
- **IO-R2, fixed** (`00de809`). `converted` now needs `origins.get(shot)`, the filter proposed. The new test is
  `test_a_helab_held_shot_read_again_from_matlabs_isnt_called_converted`: the converted TXY is cleared, the
  shot is read again from MATLAB's TXY, it isn't `converted`, and it has no HeLab origin. It fails with
  `00de809` reverted and passes with it.
- **`8145ff1`** (the Live convert test race, test only). This is a sound test fix. It waits for both the queued
  conversion and the check instead of asserting the check at the moment the conversion is queued. It is
  parametrized with `live_interval` 0, which reproduces the late-tick order. No app code changed. In five
  repeated runs the test passed 2/2 each time.
- **A~3** (the handoff's proposal for N1): I agree. It belongs to the cache area (`confirm_dataset` takes the
  signature) and doesn't block this floor.

**How "fails without the fix" was checked:** I extracted `623ce20` into `.ai/temp/rv-io2/` with `git archive`.
For each fix I reverse-applied its `helab/` diff with `patch -R`, ran its test (1 failed), then re-applied it
(1 passed).

**Checks** at `623ce20`: `test_mismatched_folders`, `test_txy_sources`, `test_live_convert`, `test_live`,
`test_live_check`, `test_quit_confirms` and `test_typing` (mypy strict and not, pyright),
`-n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-probe`: **158 passed, no RERUN**. I didn't rerun
the full suite or CI on this re-check.
