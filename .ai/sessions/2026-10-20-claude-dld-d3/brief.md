# D3: 2D density images XY / XT / YT (brief)

Worker task from the Coordinator (Tony asleep), branch `agent/dld-d3` from `1231025`
(`agent/dld-front-panel-port`). Authority: `roadmaps/dld-front-panel-port.md` (feature D3,
"Decided" section: view range per plot, axis units X/Y mm and T ms or s automatically, rates
per shot), then `.ai/sessions/2026-10-20-claude-dld-front-panel-review/notes.md` § D3 and
`lib-scripts.md` (`dld_2dplotter_window_a.m`).

Asked for:
- a `DatasetAnalysis` in `helab/scripts/standard/` (group "Basic plots v1"), drawn with
  PyQtGraph (`ImageItem` + colour bar), following the existing plots' patterns;
- projections XY, XT, YT; shared Shots; its own View range (auto-crop default or manual
  T/X/Y); bins per axis (0 = automatic); Gaussian blur σ in bins (scipy.ndimage); colour-range
  compression in the colour map only (linear / sqrt / log / power γ), colour bar in real values;
- counts, or a rate per shot (counts / shots / bin area);
- pure-NumPy compute in the worker, cancellable, empty selections and empty ranges said, not
  crashed on; result arrays visible to the plot RAM budget;
- tests, strict typing, session notes and a handoff. No X/Y rotation.
