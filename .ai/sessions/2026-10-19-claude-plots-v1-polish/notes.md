# Notes: Plots v1 polish

Worker: Claude (Fable 5.1) on the Maestri floor "Plots v1 polish", branch
`agent/plots-v1-polish`, base `c8e3a2c`. Brief: [brief.md](brief.md).
Handoff: [handoff.md](handoff.md).

## Running list of requests

| # | Request (from) | Status | Commit |
|---|---|---|---|
| 1 | Script settings: shots, view range, scatter size/opacity/cap, histogram bins/log Y (Tony, round 1) | in progress | |
| 2 | Centre hint hides while a plot dock is open (Tony, round 1) | todo | |
| 3 | Rename group "Plots" → "Basic plots v1", version from a constant (Tony, round 1) | todo | |
| 4 | Make `test_a_live_check_pauses_background_work_only_while_it_reads` deterministic (Maestro, round 1) | todo | |

## Findings

- **Centre hint never hid for the first dock.** `update_placeholder_visibility`
  tested `dock.isVisible()`. `QMainWindow.addDockWidget` shows the new dock
  through a *queued* `_q_showIfNotHidden`, so right after `_add_dock` the first
  dock is not visible yet and the hint stayed. Later docks got an explicit
  `show()` (the tabify branch), which is why a second plot hid it.
