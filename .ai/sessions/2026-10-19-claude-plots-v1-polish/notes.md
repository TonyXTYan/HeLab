# Notes: Plots v1 polish

Worker: Claude (Fable 5.1) on the Maestri floor "Plots v1 polish", branch
`agent/plots-v1-polish`, base `c8e3a2c`. Brief: [brief.md](brief.md).
Handoff: [handoff.md](handoff.md).

## Running list of requests

| # | Request (from) | Status | Commit |
|---|---|---|---|
| 1 | Script settings: shots, view range, scatter size/opacity/cap, histogram bins/log Y (Tony, round 1) | done | `18c8a27`, polish `261b7c6` |
| 2 | Centre hint hides while a plot dock is open (Tony, round 1) | done | `29cca7e` |
| 3 | Rename group "Plots" → "Basic plots v1", version from a constant (Tony, round 1) | done | `08a9927` |
| 4 | Make `test_a_live_check_pauses_background_work_only_while_it_reads` deterministic (Maestro, round 1) | done | `fe13ba9` |

## Findings

- **Centre hint never hid for the first dock.** `update_placeholder_visibility`
  tested `dock.isVisible()`. `QMainWindow.addDockWidget` shows the new dock
  through a *queued* `_q_showIfNotHidden`, so right after `_add_dock` the first
  dock is not visible yet and the hint stayed. Later docks got an explicit
  `show()` (the tabify branch), which is why a second plot hid it.
- **Live pause test.** The old test needed the other tab's 3000-file load to
  still be running when the check read, and to hit a pause checkpoint during
  the read: both speed-dependent. Two named-pipe TXY files now order the
  events: the load blocks on its pipe until the check's first `file_started`,
  and the check blocks on its last new file until the load's `paused` arrives.
  A FIFO passes the settled-age and row-completeness guards because the test
  sets its mtime 60 s back, and `_txy_complete` leaves non-regular files to the
  read.
- **pyqtgraph log axes** label the 2…9 ticks at level 0 when an axis spans
  under about two decades (`AxisItem.logTickValues` puts them first when fewer
  than three standard levels are left), so `maxTextLevel=0` can't hide them.
  Hence `DecadeLogAxis`.
- **Spin boxes**: pyqtgraph's `dec=True` with `step=0.1` steps by a tenth of
  the value's decade (`step=1` stepped 4 mm → 14 mm).

## Renders

Offscreen (`QT_QPA_PLATFORM=offscreen`, `QT_SCALE_FACTOR=2`), synthetic run:
60 shots, about 280k events, Gaussian cloud at T 3.85 s with a 2 % late tail.
The script is in the session's scratchpad, not committed. Files in
`screenshots/`:

- `settings_scatter_last_n.png`, `settings_scatter_manual.png`: the 3D
  scatter's settings tab, with "last N" chosen and then a manual range. Only
  the parameters that apply are shown.
- `txy_histograms_log_y_last_10.png`, `txy_histograms_manual_range.png`,
  `counts_per_shot_range.png`: plots with the dock's source line above them.
- `scripts_panel.png`: the group "Basic plots v1".
- `scatter_3d_last_5.html`: the scatter figure (5 shots, point size 2, opacity
  0.3, cap 20,000). QtWebEngine can't paint offscreen; open the file in a
  browser.
