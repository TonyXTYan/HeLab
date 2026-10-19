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
- Plots v1 polish (2026-10-19, `.ai/sessions/2026-10-19-claude-plots-v1-polish/`): every plot has Shots (all / last N, default 50 / range, To 0 = last); scatter and histograms have View range (auto-crop keep % or manual T/X/Y, min = max = full extent, a reversed axis uses its full extent with a ⚠ note); scatter point size, opacity and display cap; histogram bins (0 = auto) and Log Y. All three analyses are v2; the group is "Basic plots v1" (Tony's name, version from `group.py`).
- Dock source, two lines (Tony: "you can use multiple lines"): `Data source: run_042 · rev 1 · shots 51–60 (10 of 60) · helab.txy_histograms v2` / `last 10 shots · auto-crop 99 % · bins auto · log Y`; a manual range lists only the axes set; the tooltip holds the full record. The "Data source" / "Showing previously loaded data" prefix stays as the stale-plot signal.
- Tests that must hold on Windows run there too (Tony: all lab and office machines are Windows), hence `HELAB_TEST_READ_GATE` instead of named pipes.

## Open

- 99 % of all events keeps part of a flat background tail; Tony checks the crop on real data before choosing a rule.
