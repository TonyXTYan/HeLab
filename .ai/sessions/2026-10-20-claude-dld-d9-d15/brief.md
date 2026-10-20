# Brief: DLD D9 (hot-spot masks per plot) and the D15 finder placeholder

Worker task from the Coordinator ([agent workflow](../../../roadmaps/agent-workflow.md)), branch
`agent/dld-d9-d15` from `3957415` (agent/dld-front-panel-port with the merged DLD work, fixes,
Tony's ms/mm decisions and the plot polish). Commit freely; no push or merge. Authority:
[dld-front-panel-port.md](../../../roadmaps/dld-front-panel-port.md) (D9, D15, Decided "Hot spots").

1. **D9 masks per plot:** XY circles (centre, radius in mm) that keep or cut events, a shared,
   additive parameter group like Shots / View range: mode none / preset / custom, preset choice,
   custom circles as text `x,y,r[,keep|cut]` (validated, clear errors). Applied in compute before
   histogramming; in the reuse key and record; in the dock line ("mask: 3 cut circles"). Wired
   into every bundled plot that uses events (not D2, unmerged), versions bumped. Density XY draws
   the circles dashed.
2. **Presets:** the earlier detector's hot spots, un-rotated into HeLab's frame (transform and
   source documented); an empty "current detector" preset.
3. **D15 placeholder finder:** sum the XY image over the chosen shots (View range applies), flag
   bins above k × median, cluster touching bins into circles, offer them for review (record, copy
   into a plot's custom mask). Never applied automatically.
4. display_units (ms/mm), plot_text, colours.AMBER.

Acceptance: tests for keep/cut (boundary documented), several circles, invalid text, the
un-rotation round trip, every wired plot's counts, the reuse key, density's circles, the finder
on planted spots and on noise, nothing auto-applied; mypy --strict and pyright on helab and
tests, `git diff --check`; full suite clean but the two root-only failures.
