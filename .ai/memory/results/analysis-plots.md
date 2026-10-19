---
date: 2026-10-19
status: settled
name: analysis-plots
description: "First plots (v1): 3D scatter auto-crop keeps 99 % (heuristic box), 100k fixed-seed display sample, Freedman-Diaconis bins with override, analysis ID/version/file hash on every result, dock source-line format; open: crop rule on real data, units"
metadata:
  node_type: memory
  type: result
---
First plots (2026-10-19, `.ai/sessions/2026-10-19-claude-dataset-view-plots/`). Architecture is in AGENTS.md › Script system.

## Tony's defaults (2026-10-19)

- Auto-crop is configurable and keeps 99 % of the events by default; display cap 100k points; histogram bins automatic.
- Every result records the analysis ID, version and file hash, since these first plots will change.
- Placeholder script groups were replaced by working scripts only.
- Open plots should count toward the RAM budget and be evicted eventually (follow-up).

## Choices made on the floor

- Crop: a heuristic box (peel the sparsest extreme events, then narrow each axis to its exact shortest window); histogram ranges are the exact shortest window. Bounds and kept share are on the figure; bounds are derived results, Keep % is the parameter.
- Display sample: fixed seed, labelled on the figure, never the analysed data.
- PyQtGraph for 2D plots (fast redraws for Live, paints on lab PCs); Plotly only for the 3D scatter, with Open in browser.
- Axes in s and m as stored (Tony to confirm the units).
- Dock source line: `Data source: <run> · rev N · <id> vX · <params>`; the tooltip holds the full record.

## Open

- 99 % of all events keeps part of a flat background tail; Tony checks the crop on real data before choosing a rule.
