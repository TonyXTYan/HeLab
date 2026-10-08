# HeLab Roadmap

The single list of open product work, known issues and planned features.
Manual work is tracked in [.ai/MANUAL_TODO.md](.ai/MANUAL_TODO.md). Settled design
decisions live in `.ai/memory/results/`; detailed plans and reviews live in
`.ai/sessions/`.

How to use it:
- Add new items under the right heading with the date added (YYYY-MM-DD).
- When an item is done, tick it and add the commit hash, then move ticked items
  to **Done** at the next tidy-up.
- Keep each item to one or two lines; put details in a linked session note.

## Now: v0.0.5a folder browser

- [ ] Finish the status-message audit: verify load-phase labels for `merged`/
  `updated` sources ([notes](.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#status-messages)) (2026-10-08).

## Known issues

- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.

## Next

- [ ] Apply other tabs' finished status checks during Refresh without source
  I/O ([notes](.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#cross-tab-status-results)) (2026-10-08).
- [ ] Explain when disk-cache failure skips automatic status checks and offer
  a manual check (2026-10-08).
- [ ] Add small anonymized TXY fixtures with known counts/arrays, including
  interrupted and malformed writes ([notes](.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#sample-data)) (2026-10-08).
- [ ] Empty folders in lighter grey; hidden folders that contain data in black
  (from the old README list).

## Later and ideas

- [ ] Cache-only browsing: browse and view cached data while the source is
  unavailable ([notes](.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#cache-only-browsing)) (2026-10-08).
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
