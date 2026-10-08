# HeLab Roadmap

The single list of open work, known issues and planned features. Settled design
decisions live in `.ai/memory/results/`; detailed plans and reviews live in
`.ai/sessions/` and are linked from the items here.

How to use it:
- Add new items under the right heading with the date added (YYYY-MM-DD).
- When an item is done, tick it and add the commit hash, then move ticked items
  to **Done** at the next tidy-up.
- Keep each item to one or two lines; put details in a linked session note.

## Now: v0.0.5a folder browser

- [ ] Try cache first, two-step browse and Refresh on the real data volume
  (`/Volumes/dld_output`) in the full app. Also confirms whether re-selecting a
  folder held in RAM still needs the "keep the previous signature" fix
  (2026-10-08).
- [ ] Status messages: close the TODO from the Codex review once the 2026-10-08
  fixes are committed; check the load-phase labels for `merged`/`updated`
  sources ([review](.ai/sessions/2026-10-08-codex-status-message-review/review.md),
  [fixes](.ai/sessions/2026-10-08-codex-status-message-fixes/results.md)).
- [ ] Build the PyInstaller app and check the toolbar's right-pointing SVG
  triangle shows (needs Qt's SVG icon plugin in the bundle) (2026-10-08).
- [ ] Check the folder-status triangle menu by hand on native macOS: hover,
  click, Escape, and the accepted close/reopen flicker on hover-then-click
  (2026-10-08).

## Known issues

- [ ] While a tab refreshes, it ignores other tabs' finished status checks.
  Visible rows catch up when Refresh relists their parent; off-screen rows keep
  old counts until the folder is listed again. Deliberately not fixed yet: the
  quick fix (replay after Refresh) can trigger source I/O; the proper fix is
  the no-I/O path for in-memory results that cache-only browsing (below)
  needs. Two strict `xfail` tests in `tests/test_two_step_browse.py`
  (`SHARED_RESULTS_DURING_REFRESH`) record the expected behaviour and fail
  once it is fixed; remove their marker then (2026-10-08).
- [ ] If the disk cache can't be opened, automatic scans are skipped silently.
- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.
- [ ] The hover-menu tests use real timers with about 200 ms of slack and could
  flake on a slow CI machine (2026-10-08).

## Next

- [ ] Empty folders in lighter grey; hidden folders that contain data in black
  (from the old README list).
- [ ] Sample experiment data for tests (from the old README list).

## Later and ideas

- [ ] **Cache-only browsing** (name to be decided: offline mode, cached view)
  (2026-10-08). Browse and view data using only the local cache, with no
  source-folder I/O or network queries. Useful off-site or when the data
  volume is unmounted. Notes:
  - Needs persisted folder listings (subfolder names per folder). Today only
    summaries, scan history and datasets are saved; listings are session-only.
  - All source I/O goes through `FolderCache.submit`, so the mode can be one
    check there: refuse source operations and keep local-lane reads and
    in-memory replays.
  - Separate "apply a result already in memory" from "ask the source folder".
    Today both go through `request_scan(automatic=True)`, which is why Refresh
    also blocks other tabs' finished results (Known issues above).
  - Show cached dates instead of "Checking for changes…"; disable or relabel
    Refresh, Retry and Check folder status; keep generic folder icons.
  - Consider switching automatically when the data volume is unreachable,
    without blocking the GUI to find out.
- [ ] Live updates: watch the selected folder for new shots (the toolbar's
  live button is a placeholder).
- [ ] Lock the tree view during a recursive status check? (from the old README
  list; may no longer be needed).

## Done

Ticked items from the old README TODO list, kept for reference:

- [x] Automatic status check of folders in view (View menu and Settings).
- [x] Cancel a recursive status check; choose the recursion depth.
- [x] Strict typing (mypy and Pyright, run inside `pytest`).
- [x] Unit tests, run by CI on macOS, Windows and Ubuntu.
- [x] PyInstaller builds on git tags; pip caching in GitHub Actions.
- [x] File reading off the GUI thread (`IOService` and helper processes).
- [x] Slow `hasChildren()` at the root (replaced by `SnapshotFileSystemModel`).
