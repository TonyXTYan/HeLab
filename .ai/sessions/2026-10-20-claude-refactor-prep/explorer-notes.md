# Explorer track notes (2026-10-20)

Worktree `/home/user/wt/explorer`, branch `agent/refactor-explorer` from
`agent/refactor-prep` (`1429d43`). The optional, low-risk part of slice H:
Part 1, a `LiveController` out of `FolderExplorer`; Part 2, a load-state
dataclass, only if Part 1 went cleanly. Behaviour-preserving only.

## Part 1: `LiveController` (done)

**Where.** A flat module, `helab/views/explorer_live.py`, not a package
`helab/views/explorer/`. `helab/views/` is a flat folder of one module per
widget or dialog, and `FolderExplorer.py` stays where it is (about 30 test
files and three views import it by that path), so a package beside it holding
only Live would suggest a move that isn't happening. If `FolderExplorer` is
split further later (load state, summary text), a package can take all of them
at once.

**What moved** (from `helab/views/FolderExplorer.py`):

- `LiveSession` (the dataclass) and `LIVE_BLOCKED` (Live-only wording).
- `LiveController`: the state `live`, `_live_sessions`, `_reread_notes`,
  `_live_timer`, the constants `LIVE_LIST_SECONDS`, `LIVE_REREAD_SECONDS`,
  `LIVE_REREAD_NOTE_SECONDS`, and every Live method with its name unchanged:
  `watching`, `live_unavailable`, `_no_shots_yet`, `live_state`, `start_live`,
  `stop_live`, `resume_live`, `_live_changed`, `_set_browsing_enabled`,
  `_live_next`, `_live_tick`, `_live_save_blocked`, `_live_save`,
  `_live_recent`, `_live_reread`, `live_reread_note`, `_live_forget`,
  `_live_halt`, `_live_event`, `_live_display`, `_live_loaded`,
  `_live_unchanged`, `_live_observed`, `_live_save_ended`, `live_line`. Bodies
  are unchanged except that the tab's state is reached through `self.explorer`
  (two long conditions were wrapped). One accessor is new:
  `session(path)`, which the summary uses instead of reaching into
  `_live_sessions`.
- `plural` and `large_text` moved to a new `helab/views/explorer_text.py`:
  both `FolderExplorer` and the Live controller use them, and leaving them in
  `FolderExplorer.py` would make the two modules import each other.
  `FolderDetailsPanel` and `HelabMainWindow` import `large_text` from there now
  (no re-export from `FolderExplorer`). `CacheTab` keeps its own copy of
  `plural`, as before (not deduplicated: out of scope).

**What `FolderExplorer` keeps.** It creates `self.live_control =
LiveController(self)` at the place in `__init__` where the Live state and timer
were made, so the timer is still a child of the tab, made at the same point.
Thin delegating methods keep every outside caller unchanged: a `live` property
with a setter (the main window reads it; two tests assign it), `watching`,
`live_unavailable`, `live_state`, `start_live`, `stop_live`, `resume_live`,
`live_reread_note`. `live_owner` / `live_save_owner` stay on the tab: they are
the tab's owner strings, used by `foreground_owners`, `_io_event` and the main
window. `_io_event`'s first branch still routes Live's owners first, now to
`live_control._live_event`. Locking (tree, path bar, Deselect via
`_set_browsing_enabled`; Up, Refresh, Check folder status by the main window
from `explorer.live`) is unchanged.

**Judgement calls.**

- `FolderCache.saveEnded` stays connected to the tab's own
  `_live_save_ended`, which delegates. Qt then drops the connection when the
  tab is deleted, as before; connected to the controller (a plain object) it
  would outlive a tab deleted without `close_cleanup`. The timer's `timeout`
  is connected to the controller's `_live_tick`; the timer is the tab's child,
  so it goes with the tab either way.
- **The controller holds its tab weakly** (`weakref.ref`, an `explorer`
  property). The first version held it strongly, and
  `test_load_queue.py::test_load_mode_setting_and_menu_apply_to_tabs` then
  failed at teardown ("wrapped C/C++ object of type FolderExplorer has been
  deleted"), cascading into tmp-folder errors in later tests on that worker:
  the tab ↔ controller cycle kept the tab's Python wrapper alive after Qt
  deleted its tab widget, so pytest-qt's weak reference still returned it.
  Without the cycle the wrapper goes with its C++ object, as before. Anything
  else that holds a `FolderExplorer` weakly (pytest-qt, `weakref` in the app)
  would have seen the same difference.
- The controller is a plain object, not a `QObject`: a `QObject` child would
  add an object to the tab's Qt children and change nothing else.

**Tests updated** (assertions unchanged): `test_live.py` and
`test_live_plots.py` import `LiveSession` from `explorer_live` and reach the
moved privates through `explorer.live_control` (`_live_sessions`,
`_reread_notes`, `_live_halt`, `live_line`, the `LIVE_*` constants);
`test_shot_trends.py` calls `LiveController._live_halt` on its stand-in;
`test_io_trace.py`'s `LiveState` docstring names the new module. No test
patched a Live name on the `FolderExplorer` module or class
(`helab.views.FolderExplorer.store_options` is patched once, for
`place_root_state`, which stays in `FolderExplorer`).

**Docs:** `AGENTS.md`'s Live paragraph names `LiveController` /
`helab/views/explorer_live.py` (`LiveController.LIVE_REREAD_SECONDS`,
`LiveController._live_halt`). `roadmaps/refactoring.md` names no moved code;
no other doc does.

## Part 2: load-state dataclass (not done, by decision)

Stopped before starting: it would churn a lot for little gain, and would edit
a file another track is changing.

- The load fields (`loading`, `load_progress`, `load_queued`, `load_paused`,
  `load_attempt`, `load_listing`, `load_filename`, `load_checked_files`,
  `load_files`, `load_total_files`, `load_failed_files`,
  `load_unsettled_files`, `load_source`, `load_counts`, `_load_cache_pending`,
  `load_cache_reason`, `load_cache_warning`, `load_error`, `load_bytes`,
  `_load_path`, `_bg_paths`, `_dwell_path`, `_settle_wait`, `_auto_load_at`,
  `_cancelled_load_path`, `_full_check_paths`, `_listing_replaced`,
  `_unchecked_path`) are read or written about 400 times in
  `FolderExplorer.py`, about 30 times in `FolderDetailsPanel.py`, 17 in
  `HelabMainWindow.py`, about 15 in `explorer_live.py` and about 95 in tests.
- They are set field by field in `_begin_load`, the I/O event handler,
  `_display`, Cancel and Live: there is no one place that resets the group, so
  a dataclass would be a namespace (`self.load.loading`) with no behaviour or
  ownership moving into it. The state machine and its text would stay in the
  same methods.
- `HelabMainWindow.py` is being edited on the plot-UI track (slice E); its 17
  reads would be avoidable merge conflicts.

When a browser feature needs the load logic apart, the useful step is the one
the readiness note names: move the load *logic* (submit, events, Cancel,
dwell/settle) behind a controller as Live was, with the summary text as pure
functions of a load-state record, rather than a rename of the fields first.

## Validation (Part 1)

- Strict mypy on `helab` (121 files) and `tests` (94 files): clean. `pyright
  helab tests`: 0 errors.
- Targeted (`-n 2 --reruns 2`): `test_live.py`, `test_live_plots.py`,
  `test_live_io.py`, `test_live_check.py`, `test_folder_summary.py`,
  `test_folder_details_io.py`, `test_load_queue.py`, `test_two_step_browse.py`,
  `test_helabMainWindow.py`, `test_shot_trends.py`, `test_io_trace.py`: 392
  passed, 2 xfailed, no reruns (after the weakref fix; before it, the
  teardown failure above and its cascade). Also `test_cache_tab.py`,
  `test_folder_cache.py`, `test_folder_flags.py`, `test_large_folder.py`,
  `test_release_time_plot.py`, `test_root_gui.py`: 137 passed.
- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1 -q -rR`):
  **2183 passed, 9 skipped, 2 xfailed in 5 min 43 s, no RERUN lines.** The
  two warnings are pyqtgraph's NumPy 2.5 `arr.shape` deprecation in
  `test_t_spectrum.py`, unrelated.
- The moved method bodies were compared with the originals mechanically
  (`self.explorer.`/`explorer.` mapped back to `self.`): identical apart from
  the two wrapped conditions and one docstring. `LiveSession` and
  `LIVE_BLOCKED` are identical apart from the docstring naming
  `LiveController.LIVE_REREAD_SECONDS`.

## Open points

- `HelabMainWindow.py`'s import block changed by one name (`large_text` now
  from `helab/views/explorer_text.py`); the plot-UI track edits that file, so
  a trivial import conflict is possible when merging.
- `tests/test_shot_trends.py` line 34's import changed (to `LiveController`);
  the plot-UI track may change line 28's import of `ScriptTreeSelector` nearby.

## Review (coordinator, 2026-10-20)

An independent reviewer subagent read `1429d43..b031ada` and found no behavioural
regression:
- The 25 methods, `LiveSession` and the constants are AST-identical after mapping
  `self.` to the controller or the tab, and every controller write goes to a
  controller member.
- The weakref can't fail in practice: the timer is the tab's child, `saveEnded`
  stays connected to the tab, and events arrive only through the tab's guarded
  `_io_event`.
- Routing, locking, the main window and Folder details all go through the
  delegates, and no test assertion was weakened.

Two stale code comments (`io_helper.py` naming `FolderExplorer.LIVE_REREAD_SECONDS`,
`utils/events.py` naming `FolderExplorer._live_halt`) were fixed by the
coordinator.
