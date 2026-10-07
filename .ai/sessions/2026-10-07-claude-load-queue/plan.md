# Folder load queue modes

Date: 2026-10-07
Baseline: `8dbc446` on `dev/v0.0.5a`
Session folder: `.ai/sessions/2026-10-07-claude-load-queue/plan.md` (this plan is copied there as step 0)

## Context

Today, selecting another folder cancels this tab's current load. Every shot read so far is thrown away, both in RAM and on disk. Background "check for changes" scans also go to the back of the queue, so the selected row can show green RAM plus a spinner long after its data loaded.

🎓Tony wants a choice of behaviour. The selected folder should be prioritised. Earlier loads can keep running in a queue. Brief click-throughs must not flood that queue.

## Behaviour

QSettings key `load_on_select_mode`. It is exposed as an exclusive View-menu submenu "When Selecting Another Folder" and as a General-tab combo box in Settings. Both read and write the same key.

| Mode | Current load when selection moves away | Newly selected folder |
|---|---|---|
| `cancel` | Cancelled (current behaviour) | Loads immediately |
| `finish` (default) | If started: finishes in the background and writes the disk cache. If still pending: cancelled. | Loads next |
| `queue` | Started or pending: stays queued in the background | If the load queue is idle: loads immediately. Otherwise: queued at the front only after the selection stays on it for 3 s. |

- **Idle:** no unfinished load is active or pending in `IOService`. Loads that have sent `loaded` but are still writing their disk cache don't count.
- **Folder already queued in the background:** selecting it promotes it to the front immediately (no dwell) and attaches the foreground UI.
- **Context menu "Load data" (all modes):** if the path is the selected folder, load in the foreground. Otherwise, if the queue is idle, load in the background now; else append it to the background queue. Never cancels other loads, never waits for a dwell.
- **Background cap:** 8 pending loads per tab. Adding more drops the oldest pending one.
- **Cancel button and tab close:** clear the tab's background queue and dwell timer.
- **Background results:** a background load only adds the dataset to the shared memory cache (unpinned) and the disk cache. It does not change the displayed data.

## Implementation

0. **Session notes:** create `.ai/sessions/2026-10-07-claude-load-queue/` and copy this plan there.

1. **Prerequisite fixes**
   - `FolderCache._replay` (`helab/utils/folder_cache.py`): pass `priority` through to the revalidation `submit`, so the selected folder's change check goes to the front instead of the back.
   - `IOService._tick` (`helab/utils/io_service.py`): loads that have sent `loaded` (`request.completed`) get a finishing deadline of about 120 s instead of 15/20/30 s. That way blosc compression is not killed before the disk cache is written.
   - `IOService._dispatch`: completed (finishing) loads stop counting toward `MAX_ACTIVE_LOADS`. Update `test_completed_results_are_not_retried_when_helper_cleanup_times_out` to match.

2. **`IOService`**
   - `promote_load(path)`: move pending load requests for that path ahead of other pending loads. Loads otherwise stay FIFO.
   - `load_busy() -> bool`: true if any load is active or pending and has not completed. Pure memory, safe to call from the GUI thread.

3. **`FolderCache`**
   - Background loads use a second subscriber owner per tab, `f"{owner}:bg"`, through the existing `submit()`. It joins an in-flight job, so the job outlives the foreground subscription.
   - To hand a load off to the background: subscribe the background owner first, then `cancel(owner, "load")`, so `FolderCache.cancel` never sees the job with zero subscribers.
   - `promote(path)`: forwards to `IOService.promote_load` using the job's producer owner.

4. **`FolderExplorer`** (`helab/views/FolderExplorer.py`)
   - Add a `load_mode` attribute and `_bg_paths: OrderedDict[str, None]`.
   - Add a single-shot `QTimer` for the 3 s dwell. It restarts on each selection and is cancelled when selection moves away.
   - `on_selection_changed`: hand the current load off according to the mode table, then start the dwell timer only in `queue` mode when `load_busy()`.
   - `load_to_ram_cache`: in `queue` mode, while waiting for the dwell, set a "Waiting to queue (3 s)" state but don't submit. If the path is in `_bg_paths`, promote it and adopt it into the foreground: subscribe the foreground owner and remove the background subscription.
   - `_io_event`: also handle requests from the background owner. Update the row's queued/loading state and drop the path from `_bg_paths` on `loaded`/`error`/`cancelled`. Never touch `folder_opened_*` for background requests.
   - Context menu "Load data" goes through a new `request_load(path, explicit=True)`, which applies the rules above.
   - `on_stop_button_clicked` and `close_cleanup`: also cancel the background owner and stop the dwell timer.

5. **Row and status UI**
   - Add `FolderNode.load_state` (`""`, `"queued"`, `"loading"`).
   - Queued loads draw a static grey arc (or a clock icon, if one exists in `StatusIcons`) via a new model role. Active loads and scans keep the animated spinner.
   - The tooltip lists background loads and the dwell state. The existing "Queued folders" tooltip already reads `queued_load_paths()`.

6. **Settings plumbing**
   - `HelabMainWindow`: a `QActionGroup` submenu beside "Toggle Auto Load to RAM". It pushes the mode to all explorers (same pattern as `toggle_auto_load_ram`) and to new tabs in `add_new_folder_explorer_tab`.
   - `SettingsDialog`: a General-tab `QComboBox` in `load_settings`/`save_settings`. After the dialog closes, the main window re-reads the key and syncs the menu and explorers.

## Verification

- Add `tests/test_load_queue.py`, reusing the helpers from `tests/test_folder_cache.py` (`service_for_test`, `producer`, `finish_scan`, `finish_load`, `explorer_for_test`). Tests:
  - mode table per mode
  - 3 s dwell: brief click-through queues nothing; dwell queues at the front
  - idle queue loads immediately
  - background → foreground adoption keeps the job and its shots
  - context-menu load when idle vs busy
  - cap of 8 with oldest dropped
  - Cancel and tab close clear the background queue
  - background `loaded` doesn't change the displayed data
  - revalidation scan is prioritised
  - a finishing load survives more than 15 s and doesn't block the next load
- Use `qtbot.wait`/monkeypatched timers for the dwell. Tests must not use the native QSettings store; pass a tmp-dir `QSettings(path, IniFormat)`.
- Run `pytest -n 4`, `mypy helab/` and `pyright`.
- Manual check: in `python -m helab`, click quickly through about 10 large folders in each mode. Watch row states, the queue tooltip and the status bar. Confirm the last row's spinner stops once its scan completes.
