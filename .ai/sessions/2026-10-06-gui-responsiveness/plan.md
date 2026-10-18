# HeLab GUI responsiveness plan

Date: 2026-10-06
Status: Implemented for folder browsing and dataset loading. See `implementation.md` for changes, validation, and remaining verification limits.

## Objective

Keep the window responsive while opening, scanning, refreshing, and loading data from slow or unavailable filesystems. Users must be able to navigate, cancel work, retry failed operations, and close the window while a remote request remains stalled.

The GUI should display snapshots already held in memory and never wait for filesystem work. Restricting startup to the selected folder is the first improvement; reliable handling of indefinitely stalled remote operations also requires isolation from the GUI process.

## Evidence and limits

The supplied startup log selects `/Volumes/dld_output` but creates the explorer with both its model root and view path set to `/`. Startup expands `/`, `/Volumes`, and the selected folder, then launches status checks across unrelated mounted volumes. Directory checks under the selected folder continue for over a minute.

Code inspection found:

- `HelabFileSystemModel.get_visible_rows()` starts at an invalid/default model index and follows children without consulting the view root or expansion state.
- `HelabFileSystemModel.data()` reads status from the disk cache and can initiate workers during rendering.
- `HelabFileSystemModel.hasChildren()` can initiate directory checks during view queries.
- `on_rescan_cancelled()` schedules a rescan even when retry is false.
- `HelabMainWindow.closeEvent()` calls cancellation that drains worker pools using `waitForDone()` and `processEvents()`.
- `DirectoryCheckWorker.cancel()` sets a flag; it does not interrupt an active filesystem call.

These findings establish excessive work and possible sources of UI delays. They do not establish the exact call responsible for the reported sustained freeze. The provided run ended with SIGKILL, so it does not demonstrate that force termination was impossible. Default-path existence probing completed in that run, although synchronous probing remains a startup risk for an unavailable mount.

## Implementation stages

### 1. Capture the blocking operation

- Add a GUI event-loop heartbeat measured with a monotonic clock.
- Add an independent watchdog that records missed heartbeats and dumps thread stacks. A GUI timer alone cannot diagnose a blocked GUI thread.
- Record request path, operation, elapsed time, queue depth, and worker identity. Keep logging bounded.
- Use a native process sample when Python stacks end inside Qt or another native call.
- Measure delays while opening, expanding, selecting, refreshing, loading, and closing a remote folder.

Deliverable: enough evidence to distinguish GUI filesystem access, cache contention, expensive rendering, worker saturation, and shutdown waits.

### 2. Restrict startup and scanning

- Use the chosen data folder as the initial model and view root. Avoid expanding ancestors through `/` and `/Volumes` during startup.
- Preserve an explicit way to browse parents or other folders without automatically scanning their unrelated descendants.
- Gather scan targets from the current view root and expanded branches. Keep collection incremental for large trees.
- Stop parent-status propagation at the active browsing boundary.
- Combine startup refresh requests and repeated expansion events into a single scheduled scan.
- Resolve default-path availability after the window is displayed, through background filesystem work. Do not synchronously probe remote candidates at module import.
- Preserve existing user edits to the default-path candidate list.

Primary files: `helab/utils/constants.py`, `helab/views/FolderTabWidget.py`, `helab/views/FolderExplorer.py`, `helab/models/HelabFileSystemModel.py`, and `helab/models/StatusReport.py`.

### 3. Make rendering use memory only

- Maintain small snapshots of directory entries, status, counts, modification times, and RAM availability in the GUI.
- Make model queries and painting read these snapshots without disk-cache access, synchronous validation, or substantial work.
- Move filesystem queries, cache reads/writes, validation, and dataset loading into background services.
- Apply returned results on the GUI thread through queued signals to GUI-owned receivers. Workers receive plain paths and request identifiers rather than using live model APIs.
- Audit selection handlers, property panels, status updates, drive discovery, file dialogs, and plotting for blocking work. Avoid fetching large cached datasets merely to determine whether data is available.
- While retaining `QFileSystemModel`, disable custom directory icon lookup before setting its root. Evaluate watcher overhead without losing required live updates.

Primary files: `helab/models/HelabFileSystemModel.py`, `helab/models/StatusReport.py`, `helab/views/FolderExplorer.py`, `helab/views/HelabMainWindow.py`, and cache utilities.

### 4. Bound scheduling and UI updates

- Introduce a scheduler with bounded concurrency and a bounded queue. Keep remote I/O from occupying every resource used for interactive operations.
- Deduplicate requests for the same folder and operation. Prioritize the selected folder and user-requested work.
- Tag requests with tab/folder generation identifiers. Ignore results after navigation, cancellation, or tab closure.
- Coalesce repeated refreshes instead of repeatedly cancelling and restarting a scan.
- Stop automatic retries after cancellation. Use delayed, bounded retries for transient failures and an explicit Retry action after repeated failures.
- Apply model and progress updates in small batches with a time budget per event-loop turn. Collapse repeated progress notifications to the newest value.

Primary files: scan workers, `helab/utils/threading_setup.py`, and the model update throttler.

### 5. Isolate stalled remote operations

- Run potentially blocking remote filesystem operations in a helper process, including directory enumeration, metadata checks, validation, and remote file reads.
- For robust remote browsing, use a snapshot-backed `QAbstractItemModel` so Qt's internal filesystem gatherer, icon lookup, or watchers do not bypass the helper process.
- Give requests configurable deadlines. On timeout, stop waiting for results, retain the last usable snapshot, and mark the affected folder unavailable.
- Use nonblocking communication and bounded result batches. A partial result must not require the GUI to wait for a complete scan.
- Terminate or retire a stalled helper asynchronously; never wait for its termination on the GUI thread. Bound replacement attempts so a failing mount does not create unlimited helpers.
- Separate potentially expensive analysis from the GUI when it can monopolize Python execution. Keep Qt model and widget operations in the GUI process.
- Account for macOS/Windows process spawning and PyInstaller packaging. Helper entry points must not initialize the GUI or Dash server through import side effects.

Thread cancellation flags cannot interrupt an OS filesystem call. A timed-out future does not stop the underlying operation. Process isolation protects the GUI even if helper termination is delayed by the OS; it cannot guarantee responsiveness during an OS-wide stall.

### 6. Make shutdown asynchronous

- Enter a closing state first: disable scan timers, retries, auto-loading, and new submissions.
- Invalidate request generations, cancel queued work, and ignore late results before destroying their receivers.
- Replace the GUI worker-draining loop with asynchronous completion and a shutdown deadline. Avoid nested `processEvents()` loops.
- Keep caches and other resources alive until their users finish, or place their ownership in the helper process. Do not close a shared cache while active workers may still write to it.
- Close the window promptly and handle helper termination without waiting on the GUI thread.

Primary files: `helab/views/HelabMainWindow.py`, `helab/views/FolderTabWidget.py`, `helab/models/HelabFileSystemModel.py`, and `helab/utils/threading_setup.py`.

## Loading indicators and user interaction

- **Folder scan:** show an animated spinner beside a folder whose scan is queued or active. Display completed counts as results arrive. Distinguish queued work from running work in its tooltip or status text.
- **Dataset loading:** show a loading message and spinner in the plot area. Use determinate progress only when the total work is known. Keep the existing plot visible during refresh where practical.
- **Global status:** show a summary such as `Scanning 2 folders · 8 queued`, with an action to cancel relevant work.
- **Failure or timeout:** replace the spinner with `Unavailable` and a Retry action. Retain prior results with an indication that they may be stale.
- **Cancellation:** stop the visible loading state immediately and discard subsequent results from the cancelled request. Do not imply that an underlying blocked OS call has already stopped.

Animate indicators with lightweight GUI timers reading in-memory state. Emit progress asynchronously and limit its update rate. Indicators should remain active while remote operations stall; a frozen spinner is evidence that the event loop is blocked. Navigation and closing remain available while loading.

## Validation and acceptance criteria

Use controlled slow or blocked filesystem operations for repeatable checks, plus a manual run against a slow/disconnected mount. Do not depend solely on healthy local folders.

Check:

- Startup does not scan `/`, `/Volumes`, or unrelated mounts when opening the default data folder.
- Collapsed branches do not trigger recursive scans.
- Model rendering does not access the filesystem or disk cache.
- Repeated refreshes and expansions keep queues bounded.
- Navigation, tab closure, and cancellation discard stale results and never restart cancelled scans.
- Spinners continue animating during delayed work; timeouts transition to an actionable state.
- Large result batches and dataset loading do not prevent input or repainting.
- Closing during active or indefinitely blocked work does not wait for that work on the GUI thread or race cache teardown.

Initial performance targets: input response within 100–200 ms and window closure within one second under injected I/O stalls. Measure heartbeat latency under load and adjust batch/concurrency limits from evidence. These are application targets, not guarantees against OS-wide stalls.

Use focused regression checks and the project's strict typing checks during implementation. Respect intentionally disabled tests and inspect why they were disabled before changing collection or behavior.

## Delivery order

1. Instrumentation, startup/view scope, and cancellation/retry fixes.
2. Memory-only rendering and bounded scheduling with loading indicators.
3. Helper-process I/O, snapshot-backed remote browsing, and asynchronous shutdown.
4. Stalled-I/O regression checks and measured responsiveness validation.

Each stage should be independently reviewable. Completing the first stage reduces unnecessary work; it does not establish the full responsiveness objective.

## References

- [Qt QFileSystemModel performance and options](https://doc.qt.io/qt-6/qfilesystemmodel.html): directory population already uses a separate thread; custom directory icons can be expensive on network drives.
- [Qt model thread safety](https://doc.qt.io/qt-6/qabstractitemmodel.html#thread-safety): apply model changes on the model's owning thread using queued updates.
- [Python faulthandler](https://docs.python.org/3/library/faulthandler.html): thread traceback capture for diagnosing stalls.
