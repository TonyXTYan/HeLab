# Foreground/background I/O lanes, two-step browse, progress timeouts

Date: 2026-10-08
Baseline: `b40547b` on `dev/v0.0.5a`, plus the large uncommitted folder-browser work (summary panel, shared I/O queue, scan-failure history, stopping display, live-load fix).
Status: Phases 1–2 committed (`9b169c2`, `e01aeef`). Phase 3 implemented 2026-10-08 (296 passed, mypy --strict and pyright clean, uncommitted); Phase 4 next. Agreed with 🎓Tony in chat on 2026-10-08.

## Context

With the shared I/O queue at its default of 1 slot, the GUI waits behind background work:

- Expanding or selecting a folder waits for any running load, cache write, or stuck helper. On 2026-10-08, killed helpers on `/Volumes/dld_output` took ~50 s to exit and held the only slot.
- Expanding runs the full basic-scan helper. It lists the folder, stats every TXY file and every subfolder, and does 4 cache lookups per subfolder. On a network mount, even listing names can be slow, and full metadata for a large folder can take 30+ s.
- Listings use 15/20/30 s timeouts with retries. A large folder can time out while still making progress, and retries didn't help a hung volume: all 3 attempts timed out.
- A load lists and stats every TXY file before reading the first one. All of that runs under the first file's 15 s timer.

Tony's goal: **the GUI comes first.** Work for what he is looking at runs at once, and background work pauses until it's done.

## Decisions (Tony, 2026-10-08)

| Topic | Decision |
|---|---|
| Listing/scan timeout | One attempt, **60 s without progress** (helper heartbeats). No retries. |
| No-timeout retries | Only **right-click → Retry / Refresh** on the selected row and the **status-line Retry button** (same action). Bulk manual scans (Basic scan button, recursive, Refresh of many folders) use the 60 s no-progress rule. |
| Selection | Keep single selection; no multi-row select. |
| Lanes | A **foreground** lane for the current tab, plus **background** lanes from the setting. |
| Background load when B is selected (`finish` mode) | A pauses so B lists and loads first, then A resumes. |
| Paused-load cap | A paused helper keeps its background slot, so cap = the background setting. No extra cap. |
| Pause wording | **Paused** |
| Step-1 listing timeout | Records a scan failure (badge, auto-scan suppression). A manual retry then lists with no timeout. |
| Foreground scope | Current tab only. Other tabs' work is background. |
| Browse | Split into a fast step 1 (names) and a background step 2 (file details). |

## Phase 1: progress-based timeouts (done)

Implementation notes:
- Helper heartbeat event: `{"kind": "heartbeat", "phase": "listing"|"checking"|"verifying", "entries": n}`, at most once per second (`io_helper.Heartbeat`).
- Any helper event is progress, except that while a load reads a file only file events count (a repeated percentage must not hide a stalled file).
- `IOService.retries()`: only a load timing out with a current file is retried; the retry lists again under the 60 s limit. Other final timeouts: "Timed out after 60 s without progress — Retry".
- No timeout is `math.inf`; `IOService.set_timeout()` lifts a running shared job when a manual retry joins it.
- `FolderNode.retry_since`/`listed` drive "Retrying… 1 min 20 s · 3,200 entries"; the summary Cancel button and Esc cancel it.
- Loads show "Listing files… N" / "Checking files… N" before the first file.
- Failure history strips " — Retry" from reasons and shows attempt counts only for older 3-attempt records.
- AGENTS.md timeout rule already updated.


- **Helper heartbeats.**
  - `scan` sends progress (entries seen) at least every ~1 s while it works, and on each batch.
  - `load` sends progress during its listing/stat phase.
  - `IOService` resets the request's no-progress timer on any heartbeat.
- **Listings and scans** (`scan`, `resolve`): one attempt, `NO_PROGRESS_TIMEOUT = 60 s`, no retry.
  - Manual retries carry `no_timeout: True`; the deadline is skipped.
  - They show elapsed time and entries seen, and can be cancelled.
- **Loads:** the listing/stat phase uses the 60 s no-progress rule. Per-file reads keep 15/20/30 s, and `FINISH_TIMEOUT` stays 120 s.
  - The status-line Retry for a *load* error keeps the per-file timeouts. A file that hangs mid-read is genuinely stuck.
- **Failure history:** one timeout = one failure (`attempts: 1`).
  - Wording changes from "3 attempts" / "attempt N of 3" to "timed out after 60 s without progress".
  - Update the stopping-row text and the status summary.
- **Manual retry with no timeout:**
  - Right-click Retry / Refresh calls `request_scan(..., force=True)` with no timeout.
  - The status-line Retry button (`FolderExplorer._retry`) does the same for scans.
  - The "Retrying … 1 min 20 s · 3,200 entries" text is shown with a Cancel action.

## Phase 2: two-step browse (done)

Implementation notes:
- Operations: `list` (step 1, `io_helper.list_folder`), `details` (step 2) and `scan` (basic scan) — `details` and `scan` run the same full `io_helper.scan`. `folder_cache.SCANS` names all three. The model sends `request_scan(metadata_only=False)` as `list` and chains `details` on the list's `done` (`_request_details`).
- `details` is skipped when the snapshot already has details (`status["details"]`), a load job for the folder exists, or (non-manual) the folder is blocked. It runs at normal (non-priority) order, so loads and listings go first. It doesn't set the row state, prune children, or emit `directoryLoaded`; its errors do show on the row and record a failure.
- Step 2 re-lists with scandir rather than receiving names from step 1: it stays consistent with its own listing, and on Windows `DirEntry.stat()` comes free with the listing.
- The load counts raw files and subfolders in its own listing, then sends `scan_summary` and saves `folder-scan-v1` before reading files. `FolderCache._adopt_load_summary` copies signature/identity/modified into a names-only snapshot when the TXY and raw lists match; the model takes the signature on `datasetChanged`.
- Empty signature = unknown. `current_dataset` falls back to the latest dataset, the `loaded` check and data invalidation compare only known signatures, and the explorer compares TXY shot lists against the loaded fingerprint (`_changed_since_load`).
- Race fixed: a scan created before a cache clear can't restore the disk-cached flag (`FolderCache._cleared_at`).
- Tests: `tests/test_two_step_browse.py`; fixtures in the other folder tests drive `list` then `details`.


- **Step 1: names only (foreground).**
  - One `scandir`, streaming entries in batches with heartbeats; no per-file stat.
  - From names: subfolders, TXY/raw counts, matching status, empty/has-dirs. Enough for the summary, status icons and load-on-select (`_has_data`).
  - Subfolder `is_dir` uses `DirEntry.is_dir(follow_symlinks=False)` (d_type; usually no stat).
  - The summary shows "Listing… N entries" while it runs.
- **Step 2: file details (background lane, pausable between stats).**
  - TXY stats → fingerprint/signature; folder stat → modified/identity; subfolder stats → dates/identity; per-subfolder cache lookups (history, summary, disk-cache flag, cache info).
  - Saves the `folder-scan-v1` summary, and the scan-history success via `begin_scan`/`write_outcome`.
  - **Skipped** when the selected folder's load is about to run: the load computes the same fingerprint and supplies the signature.
  - Until step 2 finishes, saved summaries keep their previous signature. Step 1 must never overwrite it with `""`.
  - Freshness "Changes detected" and the Date Modified column fill in after step 2.
- **Failure:** a step-1 timeout records a scan failure (decision above). A step-2 timeout also records one.
- Blocked folders: step 1 still lists for browsing; automatic step 2 is skipped (as today for metadata-only scans).

## Phase 3: foreground and background lanes

- **Foreground lane (current tab only, outside the setting):**
  - One listing sub-slot (step 1, `resolve`) and one load sub-slot (the selected folder's load).
  - Listings take priority. The selected load pauses while a listing runs.
- **Background lanes (setting, default 1):**
  - Background loads, step 2, basic scans (manual and auto), cache writes, scan-history saves.
  - Settings label: "Simultaneous background I/O operations". Keep the `simultaneous_folder_io_operations` key.
  - Tooltip: one extra lane is reserved for browsing.
- **Yielding:** while the foreground is busy (a listing or the selected load is active or queued), running background loads and step-2 scans pause at the next file/stat, and new background work isn't dispatched.
  - A background job already in a single blocking call (one `scandir`, a cache compression) finishes alongside.
- **Pause mechanism:** cooperative, via a `pause` flag file in the request's private temp folder (`request.output`; create one for every helper, not just loads).
  - The helper checks it before each file/stat and polls every ~50 ms while it exists.
  - It sends `paused`/`resumed`. `IOService` freezes the request's no-progress timer while paused.
  - Works on macOS, Windows and the frozen app. SIGSTOP is unavailable on Windows and can't stop a call that's already stuck.
  - Resume 0.5 s after the foreground goes idle, to avoid stop–start between consecutive expands.
  - Also resume if a foreground listing has made no progress for 3 s: pausing can't help a hung volume.
- **Selecting B while A loads (`finish` mode):** A transfers to the background lane.
  - If a background slot is free, A takes it and pauses while B lists and loads, then resumes.
  - If no slot is free, stop A and requeue it. On restart it reuses shots already in RAM (`FolderCache._resume_load`), so nothing is lost.
  - `cancel` and `queue` modes keep their current meaning.
- **Paused helpers keep their background slot**, so background helpers (running + paused) never exceed the setting.
- **Hung foreground listing:** a dead helper keeps its slot until the OS lets it exit. A listing with no progress for 3 s doesn't block a new listing. Cap the foreground at 3 processes (running + stopping) so a dead mount can't pile them up.
- **Switching tabs:** the previous tab's foreground work becomes background under the same rules, and the new current tab becomes foreground.
- **Display:**
  - Summary line 2 / status line: `… · 456 loaded (37%) · Paused`.
  - Queue tooltip rows: "Paused" for paused helpers, plus foreground/background grouping.
  - Main status bar counts paused loads separately.

Implementation notes (Phase 3):
- `IORequest.lane` is set at dispatch; `IOService.is_foreground` is `FolderCache._is_foreground`: a `list`/`resolve`/`load` job with a subscriber in `FolderCache.foreground_owners`. `FolderExplorer.claim_foreground()` sets `{model.owner}` (plus `bg_owner` in queue mode) when the tab becomes current (`FolderTabWidget.on_current_tab_changed`), when the first explorer is created, and when its load mode changes; `close_cleanup` clears it.
- `_dispatch`: `_update_lanes` first (a load leaving the foreground takes a background slot or is requeued with reason `REQUEUED`, same attempt and file attempts; other work finishes as overflow), then foreground starts, then background if `_background_room()` and, for pausable operations, not `hold_background()`.
- `_apply_pauses` each tick writes/removes `<output>/pause`; every helper now gets a private folder (`payload["control"]`). `io_helper.Pause.checkpoint` runs in `Heartbeat` and before each load file. A paused request's timeout check is skipped; `resumed` refreshes `last_activity`.
- Display: `FolderExplorer.load_paused` → `loading_message`/summary "· Paused"; row load state `paused` shows the queued glyph; queue tooltip section "Paused while the current tab browses or loads"; main status bar "N loads paused"/"N scans paused"; requeued helpers show "background load to stop" / "restarts from the shots already loaded when it exits".
- Tests: `tests/test_io_lanes.py`; explorer display and load-mode tests at the end of `tests/test_load_queue.py`. A real-helper check paused a 2,000-file background load within ~40 ms of a foreground listing and resumed it 0.5 s later.

## Phase 4: measurement and docs

- Debug timing log per scan (listing time, stat time, cache lookups, entries) to confirm the split pays off on `/Volumes/dld_output`.
- Update `AGENTS.md` rules:
  - Foreground/background lanes.
  - No-progress timeouts.
  - "Navigation stays available" is true again.
  - Two-step browse.
- Update `.ai/memory/results/folder-io-queue.md`, `basic-scan-defaults-and-failures.md`, `folder-summary-indicators.md` and `project_v0.0.5a-folder-browser.md`.

## Tests to add (per phase)

- Heartbeats reset the no-progress timer. A stalled helper times out once, with no retry, and records one failure. A manual retry never times out and can be cancelled.
- Load listing phase: a slow but progressing listing does not time out.
- Step 1 gives counts/status without stats. Step 2 adds the signature and dates, and doesn't overwrite a saved signature before it finishes. Step 2 is skipped when the selected load runs.
- Lanes:
  - A listing dispatches while background slots are full or held by stuck helpers.
  - Background loads pause and resume around a foreground listing, and their timers don't advance while paused.
  - Selecting B pauses or requeues A (no slot), and A resumes with RAM shots reused.
  - A stalled listing doesn't block a new one; the foreground cap is 3.
  - Switching tabs moves foreground work to the background.
- GUI text: "Paused", "Listing… N entries", "timed out after 60 s without progress", "Retrying … elapsed".

## Order of work

Phase 1 → check in with Tony → Phase 2 → check in → Phase 3 → check in → Phase 4. Each phase leaves the suite, `mypy --strict` and `pyright helab tests` green. Nothing is committed without asking.
