# Brief: DLD plots polish (from the UI review of the merged branch)

Worker task from the Coordinator ([agent workflow](../../../roadmaps/agent-workflow.md)), branch
`agent/dld-polish` from `6a9671e` (agent/dld-front-panel-port with every DLD branch, the store
fixes and Tony's unit decisions merged). Commit freely; no push or merge.

Backlog (the review's numbering):

1. Long title lines clip plots (histograms with fits at 900 px; half gone at 560 px; the T
   spectrum's second line at ~760 px). One note per `<br>` line, short titles, full notes in the
   dock record; every bundled plot readable at a 560 px dock without clipping axes.
2. Constants editors too narrow (Folder constants showed "3.09078 ms" for 416.09078 ms; Lab tab;
   clipped wrapped name labels): width from font metrics, column stretch, dialog sized to content.
3. Histograms and Counts per shot lose zoom on Live reruns: in-place `update()`; the histograms'
   Live policy (`min_delay=1.0`).
4. One shared AMBER (and notes helper) for plot titles, the Lab tab and dialogs; "⚠ …" warnings
   amber in density, mean position, T spectrum and shot times titles; shot times must escape.
5. T spectrum's no-peak line in power mode said "(kHz/shot)²": use the amplitude unit.
6. Shot-times legend over the amber TXY-time points.
7. Mean-position record repeated the bins-left-out line.
8. Naming consistency (titles only; parameter keys unchanged).
9. Newest-shot marking for Counts per shot and Shot times.
10. Density images' log colour bar: say the colours are compressed, the numbers real.
11. Cloud-size correction: not built, skipped.

Acceptance: tests for 1, 3, 4, 5, 9; existing tests updated where titles changed; mypy/pyright
strict and `git diff --check` clean; full suite clean but the two root-only failures.
