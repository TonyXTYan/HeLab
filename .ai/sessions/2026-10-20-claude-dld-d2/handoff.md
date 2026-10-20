# Handoff: D2 per-shot trends

Branch `agent/dld-d2` (base `6a9671e`). Not pushed, not merged. Brief: [brief.md](brief.md).
Design and proposals: [notes.md](notes.md).

## Done

- **Shot trends** (Basic plots v1, `helab/scripts/standard/shot_trends.py`, `helab.shot_trends` v1):
  per shot, events in the View range's box and, per axis T/X/Y, the centre and width (threshold
  edges by default, or Gaussian fits ± SE) and optionally the temperature (the run's constants;
  Constants group like the histograms'), against shot number or shot time (raw-file time, TXY
  time as triangles with "⚠ N TXY times (no raw file)"); a moving mean ± SD band (Window N = 100);
  low-count shots amber by "fewer than 50" and/or "below 50 % of the last N shots' mean". T in
  ms, X/Y in mm, grouped ticks; all panels share the shot range (zoom/pan copied). Updates in
  place for Live. Record: counts, box, low shots, each quantity's mean ± SD, notes, computed vs
  reused; constants once (the run's).
- **Per-shot reuse** (`helab/analysis/trends.py`): a bounded, thread-safe cache by (folder, shot,
  fingerprint, settings incl. the box), and a box that stays put while Live adds shots, so a Live
  rerun estimates only the new shot(s). Live policy: every shot (the default).
- **One event point** (`helab/utils/events.py`): `notify(kind, message, …)`, hooks
  (`add_hook`), once-per-key, a 60 s rate limit per kind and folder, desktop delivery via
  `QSystemTrayIcon.showMessage`, else the status bar and the log. `is_live(path)` from the
  `LiveFeed`s. Low counts: **Notify during Live** (off by default) notifies when the newest shot,
  added by Live's revision, is low; never outside Live or for shots shown before. Live errors
  (`FolderExplorer._live_halt`) now go through the hub too (no desktop notification).

## Hooks design (for the later round, open decision 4)

- Every event is an `events.Event(kind, message, title, data, at, desktop, shown)`; kinds so far:
  `low_counts` (data: path, shot, count, delivered) and `live_error` (path, error).
- A hook is any callable taking an `Event`, added with `events.hub().add_hook(hook)` (returns its
  remover). It gets every event, including desktop ones the rate limit held back
  (`shown=False`). A failing hook is logged and never breaks the code that raised the event.
- Later: a Settings page listing kinds with actions (sound, script, remote notice), built as hooks;
  the hub's `history` (last 256) can back an event log view. New event sources call
  `events.notify` only (GUI thread).
- Suggested AGENTS.md line (Script system or Live): "Events worth telling someone about (a
  low-count shot during Live, Live stopping on an error) go through `helab/utils/events.py`
  (`notify`): hooks attach there; desktop notifications are opt-in, once per key and rate
  limited."

## On-screen checklist (Tony)

1. Plot "Shot trends" on a real run: counts row on top, centres and widths of T/X/Y below; T in
   ms, X/Y in mm with grouped ticks; band and mean line; amber low shots.
2. Zoom or pan any panel: every panel follows. Against: shot time → date axis; a run without raw
   files shows triangles and the amber note.
3. Method → Gaussian fit: error bars; first run time on a large folder (≈ 45 ms per shot) and
   whether threshold edges should stay the default.
4. Temperatures on: three more panels, sensible µK values with the lab's constants.
5. Live on a folder being written, Follow Live on: each new shot appears with one rerun; the
   dock record's "Per-shot estimates: 1 computed, N reused".
6. Notify during Live on: block the beam (or move the box) so a shot is low → one system
   notification (macOS: from the HeLab tray/menu-bar icon); more low shots within a minute → no
   more notifications, then one saying "(N more since …)". Turn Live off → none.
7. Check whether the tray icon staying in the menu bar is acceptable (proposal 7).

## Remaining / not done

- The roadmap's D2 row and `_readme.md` were not edited (the Coordinator's files).
- Release-time/velocity axes (D8) and region masks (D9) are not used here; they can be added as
  options once those land.

## Checks

- Full suite `python -m pytest -n 2 --reruns 5 --reruns-delay 1 -rR` (own basetemp):
  **2 failed, 1761 passed, 7 skipped, 2 xfailed, 10 rerun in 227.95s**; the 2 failures and all 10
  reruns are the two known root-only tests (test_constants.py::test_read_only_saved_folder_is_replaced,
  test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write). No other RERUN.
- `tests/test_shot_trends.py`: 22 tests, plus Shot trends added to the shared lists.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`: clean. `git diff --check`:
  clean.
