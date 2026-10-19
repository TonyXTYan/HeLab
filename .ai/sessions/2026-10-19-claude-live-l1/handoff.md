# Live L1 + L2 — handoff

Branch `agent/live-l1` (floor "Live L1"), base `376c7dd`. How it works, measurements and checks:
[notes.md](notes.md).

## What changed

| File | Change |
|---|---|
| `helab/io_helper.py` | `live_check` (a `load` with `live` in its payload): one folder stat while unchanged, else a names-only listing; held shots trusted (write-once), only new files stat'ed and read; `live_unchanged` or `loaded` with `memory_shots`; `RACY_SECONDS` |
| `helab/utils/io_service.py` | `IOService.live`; a Live check holds background work only while it reads a file; labels "Live check" / "Checking for new shots"; not counted in `running_loads` |
| `helab/utils/folder_cache.py` | `live_interval`, `live_autosave_shots`; `save` (deferred while the folder's save writes), `quit_saves`, `cancel_for_quit`, `saveEnded`, `quitSavesChanged`; Live summaries keep the snapshot fresh; `_drop_superseded`; `_base(prefer=)` |
| `helab/views/FolderExplorer.py` | `LiveSession`; `start_live` / `stop_live` / `resume_live`, the check/save loop, guards (no ordinary loads of the watched folder, other selections stop Live), locked tree/path bar/Deselect, the Live line (3rd summary line) and its tooltip, status-bar brief, Retry |
| `helab/views/HelabMainWindow.py` | Live action (`on_live_button_clicked`, `_update_live_action`), tab switch stops Live, settings applied, quit flow (`_wait_for_saves`, `_quit_after_saves`); also `central_hint`'s Live line and `_load_tabs` naming Live's owners. Not touched: `_set_plot_source`, `_update_plot_source_label` |
| `helab/views/QuitSaveDialog.py` | New: folders being saved, their state, Quit now |
| `helab/views/SettingsDialog.py`, `CacheTab.py` | "Live: check again after" (General, 3 s); "Live: save to the disk cache every N new shots" (Cache, 10); Reset all covers both |
| `helab/utils/constants.py` | Outside the listed paths: `LIVE_INTERVAL_SETTING`, `LIVE_AUTOSAVE_SETTING`, defaults, bounds, `read_live_interval`, `read_live_autosave` (beside the other settings readers) |
| `tests/test_live_check.py`, `tests/test_live.py` | New (7 + 17 tests) |
| `tests/test_load_queue.py`, `tests/test_folder_cache.py` | Foreground owners now include the tab's Live owner; the status-bar stub has `_update_live_action` |

Commits: `8b1b266` (L1+L2), `e9c62ae` (tooltip, hint, action test), `c0dd988` (line tidy-ups,
measurement, renders), `f410e05` (stale Retry, listing at least once a minute, notes, this
handoff), then the review fixes (below).

## Decisions taken (small judgement calls)

1. **When Live is available:** only when the tab shows the selected folder's data (loaded or
   cached, not while loading). Otherwise the action is disabled and its tooltip says why; Live
   doesn't start a load itself. A folder with no shots yet can't be watched (see open questions).
2. **The left panel stays open.** The old placeholder collapsed it and disabled the whole tab
   widget; the roadmap says greyed out, and the summary lines (Live's state, Retry) must stay
   visible. Locked: tree, path bar, Deselect, Up, Refresh, Check folder status. New Tab and the
   tab bar stay usable (switching tabs turns Live off).
3. **Errors keep Live on but stop checking** (amber "Live stopped: <why>", Retry, data shown).
   Live off then tries one save. Nothing retries by itself.
4. **Missing shots** during Live stop it like an error, and the folder is listed as mismatched as
   a load would do; turning Live off saves nothing for it.
5. **Background I/O rule:** a Live check holds background work only while it reads a file
   (measured: 15% paused / −19% throughput otherwise, 0% with the rule; notes.md).
6. **mtime test:** one stat when the folder's mtime equals the last safe one; listed when that
   mtime was within 2 s of the check (`RACY_SECONDS`), while files are still being written, and
   at least once a minute (`LIVE_LIST_SECONDS`).
7. **Held shots are trusted once the folder is shown to be the same** (TXY is written once): on a
   listing, the folder's identity and a sample of held shots are checked (review fix 2); a
   single shot rewritten in place outside the sample isn't noticed during Live, as for ordinary
   loads (the auto-save's ordinary load, which stats every file, or Retry / Refresh after Live
   will). Unreadable new files are remembered and read again only if they change.
8. **Auto-saves** are ordinary background loads; they wait while the folder's previous save
   writes or while a save of it waits for Make room / Save update. A failed save waits for N more
   new shots before trying again. Folders that can't be saved (cache off, Don't cache, RAM only,
   pending root, mismatched) never try; the line says "N not cached (RAM only)" etc.
9. **Quit window:** only Quit now; Esc and the close button keep waiting (no "back to HeLab").
   Quitting cancels other folder I/O first (`cancel_for_quit`: loads, listings, scans, icons,
   cached reads; they would be killed anyway) so saves get the lanes, and the cache's questions
   wait for the next session.
10. **Superseded datasets:** any load that reuses another dataset's arrays drops the folder's
    older datasets no tab shows (`_drop_superseded`), for ordinary incremental loads too. Without
    it every Live revision counted its shared arrays again against the RAM budget.

## Review fixes (Codex review, `review-codex.md`)

1. **Blocker — a joined save was invisible to Quit.** Fixed in `FolderCache`:
   - Save intent belongs to the subscriber, not the producer payload: `SharedJob.saves()` is true
     if any subscriber's request asked for a save, and `quit_saves()` / `cancel_for_quit()` use it.
   - `FolderCache.save` never joins another load of the folder that isn't a save (it may not
     save, or save with other cache, limit or Don't cache choices): it waits in
     `_deferred_saves` until that load and any write it starts have ended (`_save_waits`,
     started from `_forget_job` and from the writer's end), then runs with its own payload.
   - Live checks have their own job key (`("live", path)`, `SharedJob.live`), so an ordinary
     load and a Live check never join each other either (an ordinary load joining a Live check
     would have waited for a `loaded` that a `live_unchanged` check never sends).
   - Quitting now also refuses new folder work other than saves (`FolderCache.quitting`) and
     stops data-root verification: the end-to-end test showed a running `roots_verify` holding
     the only background slot, and a tab's default-folder load starting after the cancel.
   - Tests: `test_a_save_never_joins_another_load_and_quit_waits_for_it`,
     `test_every_save_subscriber_counts_for_quit`, and
     `test_quitting_straight_after_a_save_waits_for_another_tabs_load_waits_for_the_save`
     (real main window and real helpers: quit straight after the join; the save runs and lands
     in the store before the window closes).
2. **Major — held shots trusted across a changed folder.** On every listing (not on the
   one-stat path), before held arrays are reused, `live_check` checks (a) the folder's identity
   (`_folder_identity`: the nearest `.helab-root` UUID, else the mount's SMB share or device and
   the relative path) against the session's, which Live's first listing records, and (b) a
   sample of held shots against their recorded (size, mtime): the check level's sample
   (`_sample_indices`, Medium by default: first, last and max(3, 1%) random; Full checks every
   held shot). A mismatch sends `shots_missing` with `reason` root or changed: the folder is
   listed as mismatched as for a load, Live stops ("another folder is at this path now (drive or
   data root changed)" / "N shots changed in the folder"), the data shown stays and nothing is
   merged or saved. **Limit:** a single shot rewritten in place and not in the sample stays
   covered by the write-once assumption, as for ordinary loads. Tests: a replacement folder with
   the same shot numbers, and a copy under another data root (same names, sizes and mtimes), in
   the helper and through the tab.
3. **Major — a file could be read while still being written.** For Live, a new file is read
   only when it is settled by age **and** showed the same (size, mtime) on the previous check, a
   cooldown earlier (`seen`, sent back as `live_seen`); it is stat'ed again just before and after
   the read. That costs at most one check interval and doesn't rely on clocks. Files waiting for
   that count as still being written. Test: a file whose mtime looks old and stable while it is
   still growing is read only once complete. **Remaining limit:** a writer that pauses for longer
   than a check interval with unchanged metadata can still look finished; a writer-side atomic
   rename or completion marker would close it. **Ordinary loads still rely on settle age alone**
   (`_settled`, 5 s). Proposed follow-up (not in this branch): the same two-observation rule for
   ordinary loads, e.g. a file is read only if a load or scan saw the same (size, mtime) at least
   one interval earlier (kept in the session's memory per folder), or a converter-side rename.
4. **Minor — tests.** `tests/test_live_io.py` drives the real `IOService` and helper processes:
   a Live check that finds nothing never pauses another tab's background load, and one that
   reads new files pauses it only from its first read and resumes it after; and a read that never
   returns (a FIFO) times out three times, each retry starting only after the stopped helper's
   exit is confirmed, ending in the "File timed out after 3 attempts" error (POSIX only).

Checks after the fixes: full suite 923 passed, 2 skipped, 2 xfailed, no reruns; the Live tests
35/35 three times in a row under `-n 6`; `mypy --strict` (helab, tests) and `pyright helab tests`
clean.

Note: tests that build the real main window (existing ones and four new ones) resolve the
default data path, which is `/Volumes/dld_output` when mounted on this Mac, as before.

## Open questions for Tony

1. Watch a folder **before its first shot** (empty, or no TXY yet)? Needs Live to accept "no
   data yet" and the dataset view to cope with an empty dataset. Proposed for L3 with the
   dataset view.
2. **RAM during long runs:** Live's data is pinned and keeps growing; the large-folder limits
   (RAM budget/10% warn, 30% refuse) aren't applied to Live. Stop Live with a line at 30% of RAM?
3. Quit window: add **Cancel** (back to HeLab, saves go on)? Then quitting shouldn't cancel other
   tabs' work up front.
4. Should an error **turn Live off** instead (tree unlocked at once)? Kept on, so the plots stay
   the focus and Retry is one click.

## For the coordinator: proposed doc changes

### AGENTS.md — Architecture, after the Caching paragraph

> **Live** (`roadmaps/live-monitoring.md`): the toolbar's Live watches the current tab's
> selected folder once its data is shown (`FolderExplorer.start_live`, `LiveSession`); the tab's
> tree, path bar, Deselect, Up, Refresh and Check folder status are locked, and the summary's
> third line shows Live's state. A check is a `load` with `live` in its payload
> (`io_helper.live_check`, owner `<tab>:live`, foreground lane): one folder stat while the
> folder's mtime equals the last safe one (not within `RACY_SECONDS` = 2 s, no files still being
> written, listed at least once a minute), else a names-only listing. On a listing, held shots
> are reused only if the folder's identity (nearest `.helab-root`, else its location) is the one
> Live's first listing found and the check level's sample of held shots keeps its (size,
> mtime); otherwise `shots_missing` (`reason` root or changed) stops Live and lists the folder
> as mismatched. A new file is read only when settled by age and unchanged since the previous
> check (`seen`); `live_unchanged`, or `loaded` with `memory_shots` (source `updated`). Checks
> have their own job key (`("live", path)`) and hold background work only while they read a
> file. The next check starts `live_interval` after one ends (Settings → General, 3 s). New
> shots stay in RAM; every `live_autosave_shots` (Settings → Cache, 10) and when Live stops
> (Live off, another folder, tab switch or close, quit) an ordinary background load saves the
> folder (`FolderCache.save`, payload `save`); a save never joins another load of the folder
> that isn't one, and saves of one folder never overlap (`_deferred_saves`); they obey the
> budget, Don't cache and pending-save rules. Errors stop the
> checks but keep Live and the data (amber line, Retry); nothing retries by itself. Quitting
> turns Live off and waits for `FolderCache.quit_saves()` (any job a subscriber asked to save,
> waiting saves, and finished loads' `disk_cache_pending` writes) in `QuitSaveDialog`, with
> Quit now; meanwhile no other folder work starts (`FolderCache.quitting`). Live never survives a restart.
> A load that reuses another dataset's arrays drops the folder's older datasets no tab shows
> (`_drop_superseded`).

Also in the I/O rules bullet about the foreground lane, after "Navigation and loads precede bulk
scans": "A tab's Live checks run in its foreground lane but pause background work only while
they read a file."

### roadmaps/live-monitoring.md

- "Purpose and current foundation": replace "The active browser's Live action is currently a
  disabled placeholder." with "Live L1 and L2 are implemented (2026-10-19, branch
  `agent/live-l1`): the selected folder's new settled shots join its data in RAM, saved every N
  shots, when Live stops and before quitting."
- Stages table: mark L1 and L2 done (2026-10-19), pending the real-volume check.
- New section "Decided in L1/L2 (2026-10-19, worker's choices for Tony to confirm)": decisions
  1–10 above, in short.
- Open decisions: add open questions 1–4 above.

### roadmaps/_readme.md

- Known issues: tick "Quitting cancels cache writes still running in the background…" — fixed by
  the quit window (QuitSaveDialog, 2026-10-19).
- Medium term, Live monitoring: "L1 and L2 done (2026-10-19); L3 next with the dataset view".

### .ai/memory

- New `results/live-monitoring.md`: the wording settled here (Live line `Live · checked … · N
  new shots · N still being written · next check in N s · N not cached yet`; `Live stopped:
  <why>` in amber with Retry; status bar `Live <folder> · N new shots`; plot hint `Live:
  watching <folder> · N new shots`; the quit window "Saving N folders to the disk cache before
  HeLab quits:" with Quit now; Settings labels "Live: check again after" and "Live: save to the
  disk cache every N new shots"), and decisions 2, 3, 5, 9 with their reasons.
- `MEMORY.md` index line: "[Live monitoring](results/live-monitoring.md) — Live L1/L2: one stat
  per check while unchanged, new shots in RAM saved every 10 and on stop, error keeps Live on with
  Retry, quit window with Quit now".
- `results/folder-io-queue.md`: add "Live checks are foreground loads that pause background work
  only while reading a file (measured 2026-10-19: 15% paused otherwise)".

Known issues (`roadmaps/_readme.md`): add "Ordinary loads read a file once its mtime is 5 s old
(`SETTLE_SECONDS`); on SMB with stale or coarse metadata a file still being written can pass.
Live reads a new file only once it is unchanged a check later; use the same rule for loads, or
a converter-side rename/marker (2026-10-19, Live review)."

### .ai/MANUAL_TODO.md

Replace the end of "Observe new shots during writing" ("Live updates remain deferred.") with
"Live (L1/L2): see below", and add under it:

- [ ] Live on `/Volumes/dld_output` during an acquisition: turn Live on for the run folder. New
  shots appear within a few seconds of their last write (5 s settling + 3 s checks); a shot
  being written shows as "still being written"; the tree's counts follow; nothing else in that
  tab can be selected; switching tabs turns Live off.
- [ ] Note the line 3 tooltip's "The last check took … ms" for one stat and for a listing of a
  large folder over SMB; check that a new shot is found within a minute even if the SMB client
  reports the folder's mtime late.
- [ ] After 10 new shots, line 3 says "saving 10 shots", then the cache line updates; at 80% of
  the disk budget the Save update question appears and auto-saves wait for it.
- [ ] Unmount the share during Live: amber "Live stopped: Folder not found — is its drive
  connected?", data kept; Retry after remounting resumes; Live off saves.
- [ ] Quit (File › Quit and Cmd+Q) during Live and during a large folder's background save: the
  window names the folders and closes by itself; Quit now quits at once; next launch the saved
  shots come from the cache and the rest are read from the folder.
- [ ] Lab PCs (Windows): the same checks; a check's cost on the lab share.

## Notes for the dataset-view floor (L3)

- Each Live revision replaces `displayed_dataset` and emits `dataLoaded` (as any load does);
  nothing new is sent to plots. `_update_plot_source_label` will say "Showing previously loaded
  data" for plots made before a revision (their signature differs from the folder's).
- `FolderExplorer.live` (a `LiveSession` or None), `watching(path)` and `liveChanged` are the
  hooks for following Live; `session.dataset` is the newest revision.

## Manual checks still Tony's

The real-volume checks above (not run: the floor has no `/Volumes/dld_output`). Offscreen
renders of the Live line are in this folder.
