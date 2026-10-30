# Area review: `io` (I/O helpers, the queue, Live)

Reviewer 1 (Sentry, Claude Code), 2026-10-31, read-only, floor `agent/area-review` at `c3a503f`. Scope as in
`brief.md`: `helab/io_helper.py`, `helab/io_ops/` (not convert, helab_txy, stores, admin), `io_service.py`,
`folder_cache.py` (jobs, lanes, Live, RAM budget), `explorer_live.py`. Hybrid: three sub-agents read
`io_service`+`io_helper`+`infra`, `folder_cache`, and the helper ops + `explorer_live`. I re-read every code path
below and re-ran each scratch reproduction myself. The scratch tests are in `.ai/temp/io-review/` (gitignored).
Each one **fails on this tree**, which shows the defect. Run them from the floor root with:
`PYTHONPATH=tests pytest .ai/temp/io-review/<file> -p conftest -p no:cacheprovider --basetemp=.ai/temp/pytest-io-scratch -q`

**Checks run:**
- The area's 21 test files (`test_folder_cache`, `test_io_service_run`, `test_io_lanes`, `test_live*`,
  `test_load_*`, `test_mismatch*`, `test_offline_browsing`, `test_quit_confirms`, `test_saved_listings`,
  `test_scan_history`, `test_settle_setting`, `test_two_step_browse`, `test_txy_last_used_quit`,
  `test_helper_*`, `test_plot_ram_budget`), run with `-n 4 --reruns 5 --reruns-delay 1`: **528 passed, no
  RERUN**.
- `mypy helab/ --strict`: no issues in 195 files.
- `pyright helab tests`: 0 errors.

The full suite was not run, so the five Reviewers don't load one machine at once. The Coordinator runs it before
landing.

**Summary:** 8 findings (0 High, 5 Medium, 3 Low) plus 4 unverified notes. Raw TXY data is never at risk: the
worst outcomes are a cache save that never happens, Live stopping or a folder wrongly marked mismatched, and a plot
that never loads again.

---

## Findings

### io-1 · Medium · The mismatch hold also holds saves and Live checks, and quitting doesn't lift it

**Where:**
- `helab/utils/io_service.py:170` (`MISMATCH_HELD = ("load", "details", "scan")`)
- `:430-431` (`held_by_mismatch`, which goes by the operation name only)
- `:524-525` and `:536` (`_dispatch`), `:551-553` (`_apply_pauses`)
- `helab/utils/folder_cache.py:2549-2551` (`cancel_held_io` → `cancel_operations(MISMATCH_HELD)`)
- `:2849-2859` (`cancel_for_quit`, which never calls `set_mismatch_hold(False)`)

**What's wrong:** a save is a `load` with `save` (and `save_memory` for Live's save), and a Live check is a
`load` with `live`. So while the hold is on:
- a queued save or Live check never starts;
- a running one is paused (`save_held` checks `Pause.checkpoint`);
- "Cancel all loads and scans" cancels them.

This breaks the rule in `io-and-browsing.md` ("browsing, cached reads, cache saves and icons go on") and the
comment at `io_service.py:169`. `set_offline` exempts the same saves (`finishes_offline`); the hold has no such
exemption.

**Scenario:**
1. Live watches folder A.
2. A status check finds a 2nd mismatched folder, and the hold turns on. Live's checks stop silently: they are
   queued or paused, with no error.
3. The user turns Live off or quits. Live's stop-save is queued and never starts. The quit window shows
   `<A> — live, waiting` indefinitely, until the user finds the mismatch window and presses Resume, or presses
   Quit now, which drops the save.
4. If the user presses "Cancel all loads and scans" instead, the save gets `cancelled`.

**Verified:**
- Code read.
- Scratch `check_hold2.py`: with the hold on, `submit(..., "load", {"save": True, "save_memory": True})` stays
  pending (`held_by_mismatch` True) until `set_mismatch_hold(False)`.
- Scratch `check_hold.py`: `cancel_operations(MISMATCH_HELD)` sends `cancelled` to that save.
- Not run end to end through `QuitSaveDialog`.

**Test gap:** `tests/test_mismatched_folders.py` covers loads and scans only.

**Fix direction:**
- In `held_by_mismatch`, exempt saves (`payload.save`) and Live checks, or decide explicitly that Live checks are
  held and say so on the Live line.
- Have `cancel_held_io` skip saves.
- Have `cancel_for_quit` lift the hold.

### io-2 · Medium · A plot's own-source load job (`load:<choice>`) is never forgotten, so the next load of that choice hangs and leaks its arrays

**Where:**
- `helab/utils/folder_cache.py:2220-2221` and `:2304` file the job under `(f"load:{choice}", path)`.
- `SharedJob.key` (`:130-132`) returns `("load", path)`.
- `_forget_job` (`:2459-2461`) deletes only `self.jobs.get(job.key) is job`, so a choice job stays in `jobs` after
  completion, cancel or failure.
- `_invalidate_data` (`:2654-2659`) also looks up only `("load"|"live"|"cached", path)`, so a cache clear never
  cancels such a load.

**Scenario:**
1. A plot loads its own TXY source, for example "HeLab only" (`AnalysisInstance._load_source`). The load finishes.
2. Later a Reload, a source switch A → B → A, or a second plot with the same choice asks for it again.
3. `submit` joins the dead job. `_catch_up` sends `started` and nothing else, and no helper is submitted, so the
   plot shows loading for the rest of the session.
4. The same happens after a choice change while the load runs (`_end_source_load` → `cancel`).
5. The dead job keeps `job.data` and `job.base`, so its arrays stay alive after the dataset is evicted, outside
   the RAM budget.

**Verified:**
- Code read.
- Scratch `test_plot_choice_job.py`: after `loaded` and `done`, `jobs` still holds
  `('load:helab-only@m19v1', …)` with `_producers` empty, and the second submit gets only `['started']`, with
  no request pending in the service.

**Test gap:** no test submits the same plot choice twice.

**Fix direction:**
- Store the dict key on the job (`job_key`) and use it in `_forget_job`.
- Have `_invalidate_data` cancel every `load*` job of the path.

### io-3 · Medium · Live's save is cancelled when another listing moved the folder's snapshot ahead of RAM, so Live stops with "Save failed"

**Where:**
- `helab/utils/folder_cache.py:4142-4152`: a `loaded` whose signature differs from the snapshot's cancels the job
  unless `behind_listing` is set.
- `behind_listing` is set only by a `scan_summary` (`:4101-4109`), and `save_held` sends one only when it re-read
  changed shots (`helab/io_ops/save_held.py:220-226`).
- A plain save's signature covers the held shots only.

**Scenario:**
1. Live holds shots 1–2. Shot 3 lands; Live has seen it once but not read it yet.
2. Another tab's status check, details scan or load of the same folder sets the snapshot to the signature that
   includes shot 3.
3. The autosave, Live off, a tab close or quit runs `FolderCache.save`.
4. The helper answers `loaded` with the held-only signature. FolderCache cancels the job and kills the helper,
   which may be mid-write.
5. `explorer_live._live_event` (`:514-535`) shows "Save failed: Cancelled" and halts Live (amber line). At quit
   the save is simply not written.

The 2026-10-19 audit handled only a newer listing during a save that re-read shots.

**Verified:**
- Code read.
- Scratch `test_save_vs_snapshot.py`, with the real `load`, `details` and `save_held` through
  `test_live.replay`: the save's subscriber gets `['queued', 'load_source', 'cancelled']`.

**Unverified:** whether the Live tab's own background `details` of its folder can do the same with one tab.
Tracing which scans set `snapshots[live_path]` while Live is on would confirm it.

**Fix direction:**
- Always send `save_held`'s `scan_summary` and let the existing `scanned_at` rule set `behind_listing`.
- Or skip the signature check for `save_memory` jobs.

### io-4 · Medium · A Live save takes a shot Live found unreadable that the writer then finished as a mismatch: Live halts and the folder's data is dropped

**Where:**
- `helab/io_ops/save_held.py:132-137` (`changed` → `mismatch("changed", …)` unless the shot is in `recent`).
- `helab/utils/folder_cache.py:2293`: `held` is the dataset's whole fingerprint, including known-unreadable
  shots, which have no array. By contrast, `memory` at `:2272` keeps only shots in `base.data`.
- `helab/views/explorer_live.py`: `recent` comes from `LiveSession.read_at`, which records only shots that
  reached the data.

**What's wrong:**
- Live's own check sends such a shot as `known`, and when it changes it is read again like a new file (the
  documented rule). A load treats it as modified.
- Only the save treats it as a mismatch.

**Scenario:**
1. A writer pauses longer than the settle time mid-number. Live reads the file, gets a ValueError, and keeps the
   shot known-unreadable.
2. The writer finishes the file.
3. Before Live's next two checks read it, the N-shot autosave or Live off runs the save.
4. The save sends `shots_missing changed [N]`. Live halts ("1 shot changed in the folder"), and
   `FolderCache._mismatch` lists the folder as mismatched, drops its datasets from RAM and bumps the epoch.
5. The bogus mismatch also counts toward io-1's hold.

**Verified:**
- Code read.
- Scratch `test_scratch_save_held.py`: two `live_check`s give `failed_files == 1`. After the file is finished,
  `save_held(held=<fingerprint>, recent=[1])` sends `('shots_missing', 'changed', [2])`, while `live_check` with
  `known=[2 old]` simply reads shot 2.

**Fix direction:**
- In `save_held`, treat held entries with no array the way Live does: as unsettled, or read them again.
- Or have FolderCache send data shots in `held` and unreadable ones as `known`.

### io-5 · Medium · A load that finds the cache whole keeps the cached row's old signature (boundary with `cache`)

**Where:**
- `helab/io_ops/loading.py:543-546`: `whole` compares only fingerprint and origins.
- `helab/io_ops/loading.py:717-726` → `CacheStore.confirm_dataset` (`cache_store.py:1653-1687`), which updates
  names, `snapshot_at`, `unsettled` and `folder_mtime_ns`, but not the signature.

**What's wrong:**
- With HeLab's TXY in the data, the signature is computed from the folder's settled MATLAB TXY
  (`helab_txy.folder_print`), not from the fingerprint.
- Under helab-priority (the default) or helab-only, a MATLAB TXY can arrive or settle for a shot held from
  HeLab's TXY without changing the fingerprint.
- The load then sends and saves the summary with the new signature S2, but the dataset row keeps the old S1.

**Scenario:**
1. HeLab TXY exist for shots 1–3 and MATLAB TXY for 1–2. Load; the cache has S1.
2. MATLAB's TXY for shot 3 arrives. Load again: `loaded` has S2 and `cached: True`, but the row keeps S1.
3. Afterwards:
   - a cache-first check (after a restart) answers `unchanged` with S1;
   - with S2 in RAM, `_unchanged_since_cache` never applies (`loading.py:158`), so every check lists the whole
     folder.
   - It stays so until the fingerprint changes and the dataset is rewritten.

**Verified:**
- Code read.
- Scratch `test_scratch_signature.py`: the second load gives S2 with `cached True`, and the stored row still has S1.

**Unverified:** the GUI effect. A `loaded` S1 against a snapshot carrying S2 from the saved summary would be
cancelled (`folder_cache.py:4144-4152`, "Cancelled — Retry" on each cache-first selection). A FolderCache-level
test with that snapshot would confirm it.

**Fix direction:**
- Count the cache as whole only if its info signature also equals the new one.
- Or pass the signature to `confirm_dataset` (Reviewer 2's file).

### io-6 · Low · A foreground load paused by the mismatch hold keeps every background pausable request held: icons, other tabs' listings, auto-convert

**Where:** `helab/utils/io_service.py:355-360` (`_foreground_busy`) and `:362-367` (`hold_background`), used at
`:540-541` and `:552`.

**What's wrong:** `_foreground_busy` counts any unfinished foreground `load`, including one the hold has paused.
So `hold_background()` stays True for the whole hold, and every background `PAUSABLE` request (`icons`, `list`,
`convert`, `roots_verify`) is paused or kept from starting.

**Scenario:** while the selected load runs, a 2nd mismatch turns the hold on. Native icons of visible rows stop
arriving, another tab's listing stays paused, and Live's auto-convert waits, all until the user answers. The docs
say browsing and icons go on.

**Verified:** code read. Scratch `check_hold.py`: once the foreground load is paused by the hold and 0.6 s have
passed (beyond `RESUME_DELAY`), `hold_background()` is True and a new `icons` request stays pending.

**Fix direction:** have `_foreground_busy` skip requests where `held_by_mismatch(r)` is true.

### io-7 · Low · A background check beside its cached read fails with "Cached data couldn't be read — Retry" when the RAM budget evicts that read's dataset first

**Where:**
- `helab/utils/folder_cache.py`: `_evict()` at the end of the cached read's `loaded` (`:4211`) runs before
  `_resume_awaiting` (scheduled at `:2467-2469`).
- In the background nothing pins the read's dataset (`FolderExplorer._background_event` returns early for
  `cached`, `FolderExplorer.py:1286-1288`), so `_evict` (`:2113-2128`) can drop it.
- The stashed `loaded` then finds no base (`:4162-4169`) and calls `_fail_job`.

**Scenario:**
1. Select a cached folder that has new shots.
2. Leave it after the check has started reading, so in Finish or Queue mode the check and its read move to the
   background.
3. The unshown data plus plot buffers are over the RAM budget.
4. The check fails with a misleading message, its newly read shots are thrown away, and the folder's cache stays
   old.

**Verified:** scratch `test_awaiting_evicted.py`, with `max_data_bytes = 0` standing in for "over budget": the
check's subscriber gets `error: Cached data couldn't be read — Retry`. Likely only with large folders or plots
near the budget.

**Fix direction:** pin the read's dataset under the awaiting producer until `_resume_awaiting` runs.

### io-8 · Low · If removing the `pause` flag fails once, the helper stays paused for good, with its no-progress timer frozen

**Where:** `helab/utils/io_service.py:549-570`.
- `_apply_pauses` sets `request.pause_requested = False` before `_write_pause`.
- `_write_pause` swallows `OSError`.
- It is never retried, since it rewrites only when `pause != pause_requested`.
- The helper polls the flag without a limit (`helab/io_ops/infra.py:403-404`), and `_tick` skips the no-progress
  check while `paused` (`io_service.py:1057`).

**Scenario:** on Windows, an antivirus or indexer briefly holds the new `pause` file, so `os.remove` raises a
sharing violation. The background load stays "paused" and holds its slot indefinitely, and the work behind it waits.

**Verified:** code path read. The trigger is **unverified**: a test that patches `os.remove` to raise once,
then checks that the request resumes, would confirm it.

**Fix direction:** set `pause_requested` only after the write succeeds, so the next tick retries.

---

## Unverified notes (not counted)

- `folder_cache._invalidate_data` (`:2662-2664`) sets `cancelled` on queued load or cached deliveries without
  emitting `{"kind": "cancelled"}`, unlike `_mismatch` (`:2502-2505`). A waiting tab load could get `queued` and
  then nothing. A test that submits a waiting load, invalidates the path, and checks for a terminal event would
  confirm it.
- `IOService.shutdown` kills helpers from daemon `_reap` threads (`_retire`, `:984`), so if the interpreter exits
  first, a finishing save's cache write can outlive HeLab as an orphan (it ends at its next stdout write).
  Quitting during a large finishing save and checking `ps` for `helab.io_helper` would confirm it.
- `_tick` (`:1060-1064`) sends a synthetic `done` when a completed request's exit takes too long. An `error` also
  marks it completed, so a helper lingering after its `error` would get `error` and then `done`. Nobody checked
  how FolderCache takes that pair.
- A Live save's `loaded` resets `listed_at` but keeps `listed_mtime`, so the at-least-once-a-minute listing can
  slip by up to a minute after a save (pending-file path only).

## Checked and fine

- **Slots:** freed only through `_forget` on the reaper's `exited` flag, set after `process.wait()`. Removal is
  by identity (`eq=False`), so duplicate exit notifications are harmless. Cancelling during startup is safe in
  every order checked.
- **Retries:** held by `blocker()` until the predecessor in `retired` exits. `cancel`, `cancel_operations` and
  `set_offline` drop pending retries. `settle`, `trace` and cache options are stamped again at each attempt's
  `_start`.
- **Timeouts:** no-progress only. Frozen while paused and reset on `paused`/`resumed`. Held-array writes of Live
  saves and blob writes of result saves count as progress.
- **Lanes:**
  - Foreground: at most 3 processes including stopping ones, one listing and one load; a listing silent for 3 s
    stops counting.
  - Background: N slots.
  - Local: cap 2 and never paused.
  - Background work resumes 0.5 s after the foreground goes idle.
- **Work Offline:** refused at `submit`, at `_start` and in `io_helper` (`OFFLINE_REFUSED`).
  `set_offline(True)` spares `finishes_offline`/`before_offline` saves. Work Online cancels offline listings
  still in flight.
- **Cache move:** `hold_cache` keeps cache users from starting; held requests get the current cache options when
  they start.
- **Bounds:** the pending queue (128) and message queue (256) are bounded, and submits are deduplicated. The GUI
  thread never joins, waits or sleeps; `shutdown` and `cancel` only start threads.
- **`io_helper` order:** settle, then trace, then the cache-only, offline and source-guard checks, all before any
  handler. Every exception becomes `error`.
- **Settle rule:**
  - Loads leave young files out of fingerprints and signatures, stat before and after each read, and check again
    after a re-read.
  - Scans sign with `_settled`.
  - Live needs settled-by-age plus the same stat a check apart, in both the pending path and the full listing.
  - `save_held` re-reads only settled files.
  - `_raw_mtime` gives no time for young or future raw files.
  - `_quick_mtime` and Live's `racy` both read `fingerprints.RACY_SECONDS` through the module.
  - `memory_check` refuses unsettled data.
- **Source writes:** none in the scope modules; writes go only to the helper's private folder, the store or the
  index.
- **`ArtifactWriteFailed`** is a RuntimeError and escapes the `(OSError, ValueError, ParserError)` handlers, so it
  is never taken for an unreadable shot.
- **Live:**
  - Identity and sample checks hold, and `recent` shots are stat'ed besides the sample.
  - A listing at least once a minute (`since`/`listed_mtime` are sent only while `listed_at` is under 60 s old).
  - Errors stop the checks but keep Live and the data.
  - Stopping Live clears `request`, then cancels, so no late result is applied. A closed tab ignores events.
- **Late events:** routed by producer id; a forgotten job's events never reach a newer job of the same key.
  `_mismatch` fences older loads, Live checks and saves by epoch and base floor.
- **Auto-convert:**
  - One per folder.
  - `done`/`kept`/`skip` are sent only for the same profile, and the helper re-checks them against TXY present now.
  - Reasons are filtered to the current unconvertible list.
  - An error, or the offline answer followed by `cancelled`, stops auto-convert, not Live.
  - On is kept per folder for the session.
- **Live's `helab_since`:** compares profile hash and tag before trusting the old folder state.
- **Shot times:** reused only while the fingerprint and kind are unchanged.
- **Quitting:** `quitting` refuses all but saves; conversions are waited for; TXY last-use marks are flushed best
  effort.
- **RAM budget:** `_evict` skips pinned datasets and never closes plots.
- **Session dicts:** bounded (`mismatched` 8192, icons 4096) or keyed per folder with small entries.

## Lower priority

- `SharedJob.key` and the `job_key` built in `submit` (`folder_cache.py:131` vs `:2220`) are two derivations of
  one key; io-2 is the cost.
- The sub-agent for io-1, io-6 and io-8 left a few small `io-review-*` folders in the system temp folder (a
  cleanup command was denied). They are harmless and outside the repo.
