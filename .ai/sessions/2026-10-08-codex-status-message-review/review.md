# Status-message review

Reviewed the active FolderExplorer activity line, adjacent counts/cache/freshness
lines, shared queue tooltip and stopping messages, main-window status bar and the
central loading message. No application changes made during this review. The
earlier two-line scan wording change remains uncommitted.

Conclusion: several messages are accurate descriptions but selected using the
wrong state. Operation, phase and queued/running/paused/completed state need to
drive the message before wording alone can make the display reliable.

## Confirmed problems, in priority order

1. A previous basic-scan result can hide a later listing/scan error.
   `FolderExplorer._update_activity`, lines 791–804: a nonempty `_basic_result`
   selects the branch that ignores `node.error` and `root.error`. Even when new
   activity prevents replaying the result, that error-suppressing branch remains.
   Prefer current errors, with the previous scan result shown only while idle.
2. Queued and paused work can look active. The activity line tests whether scan
   requests exist, including queued requests, and ignores paused scan jobs. It
   also ignores `load_paused` when choosing the loading action. The counts line
   treats queued/running nodes alike when appending scan activity. Manual basic
   scan's `N checking` counts submitted folders including queued/paused folders.
3. The fallback `Scanning folders` also describes icon lookup and cache clearing.
   The main bar does the opposite: it can say `Ready` during those operations.
4. Load-source labels overstate what is being read or written. `merged` says
   `Reading new TXY files into disk cache` while files are read into memory; the
   cache is written after the loaded result is delivered. Both `merged` and
   `updated` can involve modified files, or no reads at all after removals/reuse.
   Their final `Loaded from ... + new TXY files` has the same limitation.
5. The load percentage measures files processed, whereas the numerator is files
   successfully loaded. Failure produces `1 of 2 files loaded (100%)`. Prefer
   `2 of 2 files checked · 1 loaded · 1 unreadable`, or distinguish completion
   percent explicitly from successful load counts.
6. `N loading in background` includes queued and paused background loads.
   Split running/queued/paused counts or say `N background loads`.
7. The main bar counts resolve as scanning, and every paused non-load as a scan
   (including icon lookup). It always includes zero-valued scan/load/queue terms
   while busy and uses `Scanning 1 folders`. Its saving count identifies every
   completed load as a cache writer, including a cache hit merely awaiting exit.

## Activity-line inventory

Source: `helab/views/FolderExplorer.py`, `_update_activity`, lines 751–805.

| Current message | Assessment | Suggested treatment |
| --- | --- | --- |
| `Queued` | Accurate for queued selected loads; ambiguous about operation. | `Load queued` or keep with operation in tooltip. |
| `Finding default folder…` | Correct for active lookup, but also used while queued. | Distinguish queued lookup. |
| `Checking for cached data` | Too broad: also shown during initial directory listing and file fingerprint checks. | Follow actual phase: listing, checking files, checking cache. |
| `Loading from disk cache` | Broadly correct for a disk-cache load, although decompression happens before source is announced. | Keep as provenance; avoid treating it as an exact phase. |
| `Reading TXY files` | Correct during source reads; wrong while paused or verifying metadata after reads. | Show pause/verification state first. |
| `Reading new TXY files into disk cache` | Wrong destination and incomplete file description. | `Reading new or modified TXY files…` during reads, then `Saving data cache…`. |
| `Reading new TXY files` | Omits modified files and can appear when no files need reading. | Base action on actual reuse/read counts. |
| `Reusing data in memory` | Correct for memory reuse; usually delivered immediately. | Keep. |
| `Scanning: checking file counts and status…` | Correct for active metadata scans. Also shown for queued scans/listings/details without phase/state distinction. | Preserve agreed wording for running scans; use queued/paused/listing wording for other states. |
| `Scanning folders` | Unrelated operation fallback. | Explicit icon/cache-clear labels; use idle text when nothing user-visible is happening. |
| `Ready` | Reasonable for idle selected-folder state, including usable data while cache saving continues. | Clarify scope where background activity is present. |
| `Ready · Loaded from memory/disk cache/TXY files` | Accurate provenance when current data is displayed. A partial load can still say Ready; unreadable count is in the summary. | Keep, optionally include a brief partial-load outcome. |
| `Ready · Loaded from disk cache/memory + new TXY files` | Can omit modifications or imply reads that did not occur. | Use real counts, or `Loaded using cached data` with details in tooltip. |
| Appended cache miss/read reason | Usually accurate at the time of loading; can persist after a cache is subsequently created. | Keep historical reason in tooltip. |
| `Waiting 3 s before queueing` | Correct dwell policy, but fixed total does not show remaining time. | `Queues if still selected after 3 s` matches the central message. |
| `N loading in background` | Includes queued/paused loads. | `N background loads`, or state-specific counts. |
| `Basic scan: N scanned · M checking · F failed` | Completed/failed counts are useful; checking is submitted, not necessarily running. Overrides concurrent load text. | `M pending`, or separate queued/running/paused; retain concurrent load indication. |
| `Basic scan complete · N scanned · F failed` | Correct batch outcome; can hide later errors. | Show only while idle and no current error. |
| `Basic scan cancelled · N scanned` | Accurate for cancellation of this tab's scan subscriptions. | Keep; stopping text explains any process still exiting. |
| `N queued` | Global operation count in a local line, not just scans/loads or this tab. | `N operations queued` and identify app-wide scope in tooltip. |
| Error text | Usually useful, but old basic-scan results can suppress it; errors can also suppress stopping/queue suffixes. | Prioritize current errors and retain actionable waiting state. |

## Loading/central-message inventory

Source: `FolderExplorer.loading_message`, lines 718–732;
`HelabMainWindow._central_placeholder_loading_indicator`, lines 995–1018.

| Current message | Assessment |
| --- | --- |
| `Preparing…` | Safe general starting state. More specific phase is useful when known. |
| `Listing files… N` | Heartbeat counts directory entries, including raw/unrelated entries, not only TXY files. Prefer `Listing folder… N entries`. |
| `Checking files… N` | Correct for fingerprint checks before loading. Verification heartbeats after progress exists are ignored, leaving a stale read/progress message. |
| `Retrying… (attempt N of 3)` | Per-file attempt, not three attempts at the whole folder. Prefer `Retrying file…` with filename/details in tooltip. Queued retry instead says Queued, with the waiting cause in stopping text. |
| `N of M files loaded (P%) · F unreadable` | Counts are accurate, but percentage includes failures. Distinguish processed from successfully loaded. |
| Bare `P%` | Legacy fallback when total count is unavailable; no unit/context. Prefer `Loading… P%`. |
| `· Paused` | Correct and present in central progress/tooltip, missing from the activity-line action. |
| `Loading <folder>` | Remains present while paused. Could use `Loading paused: <folder>`. |
| `Queues if still selected after 3 s` | Correct description of dwell policy. |
| `Loaded <folder> · size` | Correct delivered-data outcome; detailed counts indicate unreadable shots. |
| `Scanning…` | Also used for a queued node. Should distinguish queued vs running. |
| `Select a data folder` | Reasonable idle guidance. |

## Folder-summary lines

Source: `FolderExplorer._update_folder_summary`, lines 833–956;
`_update_cache_summary`, lines 962–1016.

| Message family | Assessment |
| --- | --- |
| `Selected: <relative path>` | Correct selected-vs-viewed scope. |
| `N TXY found · M loaded/P%/unreadable` | Useful counts; progress percentage issue above also applies here. |
| `Previously loaded`, `Previous data`, `Changes detected` | Correct distinction between displayed arrays and current folder observations. Fingerprints compare file metadata, not parsed TXY contents. |
| `Not loaded` | Correct when no displayed dataset for that folder. |
| `TXY count not checked · Retry manually` | Useful for blocked/skipped scan without a report. |
| `Could not check folder · Retry` | Correct generic failure guidance; exact reason is in tooltip. |
| `Listing… N entries` | Correct entry count, but queued/running distinction remains relevant. |
| `Scanning folder content for TXY files…` | Generic unknown-report fallback; under-describes raw-shot matching and metadata scan. Align with agreed scan wording when actually running. |
| `N raw shots found · No converted TXY files` | Correct. |
| `Folder is empty` | Correct observed snapshot; freshness line indicates observation age. |
| `No TXY files here · Select a subfolder to load data` | Reasonable if subfolders exist; does not promise those subfolders contain TXY files. |
| `No TXY files in this folder` | Correct observed snapshot. |
| `Refresh failed · Retry` | Reasonable retained-counts failure marker. |
| `Retrying… elapsed · N entries` | Timer includes time queued before retry starts. Use `Retry queued` vs `Retrying` if waiting. |
| `Checking file counts and status…` | Accurate active scan purpose, but appended for queued nodes as well. |
| `Cached data found/loaded · Cached age` | Useful distinction; available cache and data origin are observations, not a promise of current validity. Tooltip explains. |
| `Updating/Creating cache…` | Correct from tracked pending disk-cache writer state. |
| `Cache update/creation failed` | Correct retained-error outcome. |
| `Cache updated/created age` | Correct saved metadata outcome. |
| `No cached data` | Correct last observation; tooltip appropriately qualifies availability. |
| `Status scan: age` | Correct observed scan age; exact time is in tooltip. |
| `May be outdated`, `Freshness unknown` | Appropriately cautious metadata hints. |
| `Changes detected` in cache line | Supported by later TXY fingerprint difference, not an assumption from folder age. |
| `Live updates off` | Accurate: active-browser Live action is disabled. Auto first scans are not continuous monitoring. |
| `Basic scan failed age · Retry manually` | Correct persisted suppression/outcome. |

## Main status bar and shared tooltip

Source: `HelabMainWindow.update_status_bar_left`, lines 140–159;
`IOService.stopping_summary` and `queue_tooltip`, lines 365–407.

| Message family | Assessment |
| --- | --- |
| `Scanning N folders` | Groups listing/details/basic scan/lookup; lookup is not a scan. Counts completed scans awaiting exit too. Fix singular/plural and omit zero-valued terms. |
| `Loading N datasets` | Excludes completed and paused loads correctly. Keep. |
| `N loads paused` | Correct, but can include a completed cache-writing load that pauses while rereading memory-held shots for cache completeness. Label actual operation phase. |
| `N scans paused` | Counts all paused non-load operations, including icons. Use operation-specific counts. |
| `Saving N caches` | Completed load is only a proxy: a cache-hit load can be counted despite having no cache write. Track actual pending writers. |
| `N queued` | Excludes held requests as intended; operation count across the app. Use clearer noun. |
| `Ready` | Omits running icon, cache-clear and history-save operations; cache clear is a meaningful omission. |
| `Waiting for cancelled/timed-out <operation> to stop (age)` | Accurate distinction between cancellation/timeout and confirmed process exit. Keep. |
| `Retry N of 3 waiting for timed-out load to stop` | Accurate scheduler wait; make per-file retry scope clearer in tooltip. |
| `Waiting for background load to stop` | Requeued load is being stopped to free its slot, not merely all background work. Prefer `Moving load to background: waiting for it to stop`. |
| `N more stopping` | Accurate additional retired-helper count. |
| Queue tooltip: operation/path, timeout, stop duration, retry/requeue explanation | Detailed and generally accurate. `Queued folders` actually lists operations. Dispatch uses lanes, so `next first` is not a promise of exact global start order. Prefer `Queued operations`. |
| Pause tooltip: current tab browsing/loading | Accurate cooperative pause reason, including short resume delay. |
| Slow-stop tooltip: unresponsive volume | Qualified with `usually`; reasonable explanation, not a confirmed diagnosis. |
| `CPU app/system · RAM app/system` | Values measure the GUI process vs system, excluding isolated helper subprocesses from app totals. Clarify process scope in tooltip. CPU percentages sum per-core utilization and can exceed 100%. |
| Startup `Please wait. GUI loading... version/hash` | Correct transient startup state. |
| `Select and load a data folder first` | Correct prerequisite for the corresponding plotting action. |

Error families also include no TXY files, no readable TXY files, input/snapshot
limits, source changes during loading, queue full, unexpected helper exit, raw
filesystem exceptions, timeout and cancellation. Their core reasons match the
throwing branches. `Folder changed while loading — Refresh to retry` would be
clearer as `Folder changed while loading — Retry load`: Retry preserves the
intended load path, whereas toolbar Refresh also relists the viewed/visible
folders and refreshes their icons.

## Validation

Used a temporary isolated Qt harness at `/private/tmp/helab_status_audit.py`.
It calls the real formatters with controlled queued, paused, failed, completed
and operation-specific states. No source folders, native settings writes or
helper jobs were used. Dash startup was stubbed to avoid the running app's port.
Representative output:

```text
Queued scan: Scanning: checking file counts and status…
Only icon lookup: Scanning folders
Only cache clear: Scanning folders
Paused file load: Reading TXY files
Merged load before cache write: Reading new TXY files into disk cache
Only queued background load: Ready · 1 loading in background
Later listing failure after basic scan result: Basic scan complete · 1 scanned · 0 failed
Partial load completion: 1 of 2 files loaded (100%) · 1 unreadable
Global active cache clear: Ready
Global active icon lookup: Ready
Global paused icon lookup: Scanning 0 folders · Loading 0 datasets · 1 scan paused · 0 queued
Global default-folder lookup: Scanning 1 folders · Loading 0 datasets · 0 queued
Global cache-hit load awaiting exit: Scanning 0 folders · Loading 0 datasets · Saving 1 cache · 0 queued
```

This verifies message selection in controlled states, not a full live GUI run.
Recommended next change: drive message selection from operation, phase and state;
prioritize current errors; keep agreed scan wording for actual active scans;
separate successful-load counts from completion progress; retain useful tooltip
details without exposing scheduler architecture in the status line.
