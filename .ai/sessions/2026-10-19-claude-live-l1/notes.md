# Live L1 + L2 — session notes

Floor "Live L1", branch `agent/live-l1`, base `376c7dd` (dev/v0.0.6 + briefs). Worker: Claude
(Opus 5.5). Brief: [brief.md](brief.md). Handoff: [handoff.md](handoff.md).

## How it works

**Turning it on.** The toolbar's Live (`HelabMainWindow.action_tab_live`) follows the current tab
(`_update_live_action`, every status-bar tick and on `FolderExplorer.liveChanged`). It is enabled
when the tab shows the selected folder's data; otherwise it is disabled and its tooltip says why
(`FolderExplorer.live_unavailable`: no data shown, still loading, or mismatched cached data). A
start that fails anyway shows the reason as a status-bar notice.

**While on.** `FolderExplorer.live` is a `LiveSession`. The tree, path bar and Deselect are
disabled; Up, Refresh and Check folder status too (New Tab stays: switching tabs turns Live off).
The left panel no longer collapses (the old placeholder did): the summary lines must stay visible.
Line 3 ("Live updates off") becomes the Live line, e.g.

    Live · checked just now · 1 new shot · 1 still being written · next check in 1 s · 1 not cached yet

with a tooltip (watching since, checks, last check's duration and whether it listed, new shots,
not yet cached, how often it saves, last save, why it can't save). The status bar says
`Live <folder> · N new shots`; the plot-area hint `Live: watching <folder> · N new shots`.
Renders: [live-on.png](live-on.png), [live-stopped.png](live-stopped.png).

**A check** is a `load` with `live: True` in its payload, in the foreground lane, owner
`<tab>:live`, keyed `("live", path)` in `FolderCache.jobs`. `FolderCache.submit` adds the shots
held in RAM (`memory`, from the shown dataset:
`prefer_base`). `io_helper.live_check`:

1. `stat` the folder. If its mtime equals what the previous check called safe (`live_since`),
   nothing was added or removed: `live_unchanged`, done.
2. Else list by name (`scandir`, no stats). Held shots the folder no longer lists:
   `shots_missing`. The folder must still be the session's (`_folder_identity`: nearest
   `.helab-root` UUID, else its location) and the check level's sample of held shots must keep
   its (size, mtime); else `shots_missing` with `reason` root or changed. The rest of the held
   shots are trusted (TXY is written once).
3. Stat only the files not held. A file is read only when settled by age (`SETTLE_SECONDS`)
   and unchanged since the previous check saw it (`seen` → `live_seen`); the others count as
   still being written. Known-unreadable files that haven't changed are skipped (`known`).
4. Nothing to read: `live_unchanged`. Else read them (pandas, as a load does; stat'ed again
   just before and after; a file that changes while read is left for later), send
   `scan_summary` and `loaded` with `memory_shots` and source `updated`, as an incremental load
   does. FolderCache merges as for any load.

`live_since` is the folder's mtime_ns, or None (list next time) when it is within 2 s of now
(`RACY_SECONDS`: another change could share its timestamp tick, or the server's clock is ahead)
or when files are still being written (they settle without changing the folder's mtime). The
explorer also sends None once a minute (`LIVE_LIST_SECONDS`): a network drive may report a
folder's mtime late (SMB clients cache it for seconds), so a missed change waits at most that.

The next check starts `live_interval` seconds (Settings → General, default 3 s) after a check
ends. Nothing runs while a check or save is in flight, so checks never overlap or queue.

**Saving (L2).** New shots stay in RAM (`session.unsaved`). Once `live_autosave_shots` (Settings →
Cache, default 10) wait and the folder isn't being saved (nor waiting for a Make room / Save
update answer), the next step is a save instead of a check: `FolderCache.save` submits an ordinary
load (payload `save: True`, owner `<tab>:live-save`, background lane). It lists and checks the
folder like any load, unpacks the cached dataset, re-reads the new shots it lacks, delivers
`loaded` (Live goes on from there) and then writes the dataset in the background, under the
budget, Don't cache and pending-save rules of every load save. `FolderCache.saveEnded(path,
outcome)` reports how the write ended. A failed save puts its shots back and waits for N more
before trying again; a folder that can't be saved (disk cache off, Don't cache, RAM only,
pending root, mismatched, or a save that found the cache unwritable) isn't tried: the line says
`N not cached (RAM only)` etc.

**Stopping.** Live off, selecting or opening another folder, Deselect, switching tabs, closing
the tab, and quitting all stop Live and save what's unsaved (`stop_live`). A save of a folder
whose previous save is still writing waits for it (`FolderCache._deferred_saves`), so saves of
one folder never overlap. The session (`_live_sessions`) lives until its saves end.

**Errors.** A failed check or save (folder gone, timeout, missing shots, too large) stops
checking but keeps Live on and the data shown: line 3 turns amber, `Live stopped: <why>`, with
Retry on line 1 (`resume_live`: lists the folder again). Nothing retries by itself. Live off then
tries one save.

**Quit.** `closeEvent` stops Live in every tab (saving), and if `FolderCache.quit_saves()` is not
empty (Live saves not yet read, deferred, or any finished load's `disk_cache_pending` write) it
cancels other folder I/O (`cancel_for_quit`), detaches the cache questions (they come back next
session from the store) and opens `QuitSaveDialog`: folder names with their state, closing by
itself when the saves end; **Quit now** skips them; Esc and the close button keep waiting.
Each save stops itself after the usual no-progress timeouts (60 s listing, 15/20/30 s per file,
120 s while writing). Live never survives a restart (no setting saves it).

## After the Codex review

See handoff.md › Review fixes. In short: a save never joins another load of its folder and save
intent is tracked per subscriber (quit sees it); Live checks have their own job key; on a
listing, held shots are reused only from the same folder (identity + sampled fingerprints); a
new file is read only once unchanged a check later; quitting starts no other folder work. The
check now also stats the held sample on listings (Medium: 2 + max(3, 1%) files): for 10,000
held shots that is 102 stats per listing, once a minute or when the folder changes.

## Foreground lane: measured, and the rule chosen

[measure_live.py](measure_live.py) runs real helpers through `IOService` on this Mac (APFS);
output in [measure_live.out](measure_live.out):

| Folder | Unchanged (one stat) | Listed, nothing new | One new file |
|---|---|---|---|
| 100 files | 38 ms (helper 0.0 ms) | 39 ms (0.2 ms) | 198 ms (159 ms) |
| 1,000 | 39 ms (0.1 ms) | 39 ms (1.0 ms) | 198 ms (156 ms) |
| 10,000 | 39 ms (1.4 ms) | 39 ms (9.7 ms) | 200 ms (165 ms) |

End to end is the helper process (~35 ms) plus the 20 ms service tick; a new file adds the
numpy/pandas import (~150 ms) and its read. On SMB the stat is one round trip, while a listing of
a large folder is many; that is what the mtime test saves. Real-volume numbers are Tony's.

Background loads running back to back, with Live checks every 3 s (every third finding a shot):

| Rule | Background paused | Background rate |
|---|---|---|
| No Live | 0% | 867 files/s |
| Checks hold background work like any foreground load | 15% (8 pauses in 30 s) | 700 files/s |
| **Chosen: only while a check reads a file** | 0% | 867 files/s |

`IOService._foreground_busy` counts a Live check only while `current_file` is set (a TXY being
read), so a check that finds nothing never pauses other tabs' work, and one that reads a few new
files pauses it for that read plus the usual 0.5 s resume. Live checks are labelled "Live check"
in the I/O tooltip and "Checking for new shots" in the activity summary, and aren't counted as
"Loading …".

## Other changes worth knowing

- `FolderCache._drop_superseded`: a dataset built on another's arrays (`memory_shots`: a Live
  check, an incremental update) drops the folder's older datasets no tab shows. Without it every
  Live revision stayed in `datasets` and counted its shared arrays again against the RAM budget,
  evicting other folders. Applies to ordinary incremental loads too.
- `FolderCache._adopt_load_summary(live=True)`: a Live check's summary updates the folder's
  snapshot and marks it freshly listed, so tabs update the tree's counts from memory instead of
  listing the folder (and running a details scan) after every new shot.
- `FolderCache._base(prefer=…)`: the base for a Live check is the dataset the tab shows.
- `FolderExplorer.foreground_owners()` always includes `<tab>:live` (the current tab's checks).
- `FolderExplorer.load_to_ram_cache` does nothing for the watched folder; `_status_ready` and
  `_shared_dataset_changed` don't drop its shown data.

## Checks run

- `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 912 passed, 2 skipped,
  2 xfailed, no reruns (twice, after each commit). `tests/test_typing.py` passes.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`: clean.
- New tests: `tests/test_live_check.py` (helper: one stat, trusted held shots, unsettled files,
  racy mtime, unreadable files, missing shots, missing folder) and `tests/test_live.py` (17:
  the whole flow with auto-save and stop save checked in the real store, settling, error and
  Retry, missing shots, navigation guards, Don't cache, tab close, tab switch, saves not
  overlapping, the quit window and Quit now, a finished load's save as a quit save, the real
  main window's close and Quit now, the Live action, the hold rule, settings).
- Offscreen renders with real helpers against the floor's private cache (`floor-env.sh`).
